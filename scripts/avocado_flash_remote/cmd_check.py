"""``check`` subcommand: the read-only pre-flight.

Ports the bash kit's ``preflight.sh``. Every assertion the profile lists is
run through a read-only ``Ops`` and prints one ``PASS``/``FAIL`` line;
``INFO`` lines are informational and never counted.

Counting differs from the kit on purpose. The kit's ``checks: N/M`` counts
checks that PASSED, so a single failing check printed ``13/14``. Here N is
the number of checks that were EXAMINED (produced a PASS or FAIL verdict) and
M the number the profile lists, so a failing check still counts toward N and
only a check that could not run lowers it. A check that could not run (the
tool failed, an input was unreadable, the name has no implementation) is
printed as ``FAIL  <label>: not examined: <reason>`` and fails the run:

* exit 0 - every check passed and N == M (and M > 0);
* exit 1 - at least one check returned FAIL;
* exit 2 - nothing failed but at least one check was not examined.

This module only calls ``Ops`` read verbs and reads efivarfs through
``efi``; it must stay free of ``subprocess`` and ``os`` mutations so it is
safe under ``ReadOnlyOps``.

Standard library only (ships to a board running Python 3.10).
"""

from __future__ import annotations

import glob
import os
import re
from dataclasses import dataclass, field
from typing import Callable

from . import efi
from .arm import entries_with_label
from .ops import OpFailed, Ops, OpsError

DEFAULT_EFIVARS_DIR = "/sys/firmware/efi/efivars"
HEADER = "== read-only pre-flight; informational lines are marked INFO and are not counted =="
MANIFEST = "MANIFEST.hashes"

_SUM_RE = re.compile(r"^([0-9a-fA-F]{64})[ \t][ *](.+)$")
_NO_TABLE_RE = re.compile(r"recognized partition table|no partition table")
_CREATE_ONLY_RE = re.compile(r"(^|\s)-C([\s,|]|$)|--create-only")
_READ_ERRORS = (OpsError, OSError, ValueError)


@dataclass
class CheckResult:
    exit_code: int
    examined: int
    total: int
    lines: list = field(default_factory=list)


class NotExamined(Exception):
    """A check could not run; the run fails with no verdict for it."""


class _Ctx:
    """Inputs shared by checks, with each expensive read done once."""

    def __init__(self, ops: Ops, profile, staging_dir, efivars_dir, expected_boot_order):
        self.ops = ops
        self.profile = profile
        self.staging_dir = str(staging_dir)
        self.efivars_dir = str(efivars_dir)
        self.expected_boot_order = expected_boot_order
        self.device = profile.target.device
        self.base = os.path.basename(self.device)
        self._cache: dict = {}

    def once(self, key, fn):
        """Compute ``fn()`` once; a failure is cached and re-raised."""
        if key not in self._cache:
            try:
                self._cache[key] = (True, fn())
            except _READ_ERRORS as exc:
                self._cache[key] = (False, exc)
        ok, val = self._cache[key]
        if not ok:
            raise val
        return val

    def efi_list(self) -> str:
        return self.once("efi", self.ops.efibootmgr_list)

    def efi_field(self, name):
        for ln in self.efi_list().splitlines():
            m = re.match(rf"^{name}:\s*(.*)$", ln)
            if m:
                return m.group(1).strip()
        return ""

    def device_present(self) -> bool:
        def probe():
            res = self.ops.lsblk(self.device, columns="TYPE")
            return res.rc == 0 and "disk" in res.text.split()

        return self.once("present", probe)

    def require_device(self):
        if not self.device_present():
            raise NotExamined(f"{self.device} is absent")

    def manifest_names(self) -> list:
        def load():
            raw = self.ops.read_file(f"{self.staging_dir}/{MANIFEST}")
            names = []
            for ln in raw.decode("utf-8", errors="replace").splitlines():
                m = _SUM_RE.match(ln.rstrip("\r"))
                if m:
                    n = m.group(2)
                    names.append(n[2:] if n.startswith("./") else n)
            return names

        return self.once("manifest", load)


# ------------------------------------------------------------------ checks
# Each returns (ok, detail) or raises NotExamined / a read error.


def _emmc_exists(c: _Ctx):
    return c.device_present(), c.device


def _target_identity(c: _Ctx):
    ident = c.profile.target.identity
    if ident.kind == "sysfs-name":
        ok = c.base == ident.value
        return ok, f"sysfs name {c.base}" + ("" if ok else f" (expected {ident.value})")
    if ident.kind == "serial":
        attr = ident.sysfs_attr or "serial"
        raw = c.ops.read_file(f"/sys/block/{c.base}/device/{attr}")
        got = raw.decode("utf-8", errors="replace").strip()
        return got == ident.value, f"{attr} {got!r} (expected {ident.value!r})"
    if ident.kind == "by-path":
        link = f"/dev/disk/by-path/{ident.value}"
        res = c.ops.run_read(["ls", "-l", link], check=False)
        if res.rc != 0:
            return False, f"{link} not found"
        target = res.text.rsplit("->", 1)[-1].strip() if "->" in res.text else ""
        got = os.path.basename(target)
        return got == c.base, f"{link} -> {got or '?'} (expected {c.base})"
    raise NotExamined(f"unknown identity kind {ident.kind!r}")


def _not_read_only(c: _Ctx):
    c.require_device()
    ro = c.ops.blockdev_getro(c.device)
    return ro == 0, f"blockdev --getro: {ro} (rc=0)"


def _sector_count(c: _Ctx):
    c.require_device()
    expect = c.profile.target.sectors
    sectors = c.ops.blockdev_getsz(c.device)
    return sectors == expect, f"{sectors} (expected {expect})"


# devtool-debt: this check and the lsblk sibling checks (device_present) treat a tool failure as a verdict.
# Ceiling: a board whose lsblk or sfdisk fails for an unrelated reason reports the wrong cause.
# Upgrade trigger: the first false verdict seen on a board.
def _no_partition_table(c: _Ctx):
    c.require_device()
    res = c.ops.sfdisk_dump(c.device)
    text = res.text + res.stderr
    if res.rc != 0 and _NO_TABLE_RE.search(text):
        return True, "sfdisk --dump reports no partition table"
    if res.rc == 0:
        return False, "a partition table is present (sfdisk --dump succeeded)"
    first = text.strip().splitlines()[0] if text.strip() else ""
    return False, f"sfdisk --dump failed rc={res.rc}: {first}"


def _not_mounted(c: _Ctx):
    c.require_device()
    rx = re.compile(rf"^/dev/{re.escape(c.base)}(p[0-9]+)?$")
    hits = [ln.strip() for ln in c.ops.findmnt_source() if rx.match(ln.strip())]
    if hits:
        return False, f"{hits[0]} is mounted"
    return True, f"no {c.base} source in findmnt"


def _supports_create(c: _Ctx):
    res = c.ops.efibootmgr_help()
    if res.rc != 0:
        first = (res.stderr.strip().splitlines() or [""])[0]
        raise NotExamined(f"efibootmgr --help failed rc={res.rc}: {first}".rstrip(": "))
    ok = bool(_CREATE_ONLY_RE.search(res.text + res.stderr))
    return ok, "-C listed in --help" if ok else "-C not listed in --help (-c would add to BootOrder)"


def _boot_order(c: _Ctx):
    if c.expected_boot_order is None:
        raise NotExamined("no expected BootOrder supplied")
    actual = c.efi_field("BootOrder")
    return actual == c.expected_boot_order, f"actual '{actual or '<none>'}' (expected {c.expected_boot_order})"


def _boot_next(c: _Ctx):
    nxt = c.efi_field("BootNext")
    if nxt:
        return False, f"BootNext is set to {nxt} (someone's one-shot)"
    return True, "unset"


def _oneshot_label(c: _Ctx):
    params = c.profile.arm.params
    label = params.get("label") if hasattr(params, "get") else None
    if not label:
        raise NotExamined("profile arm declares no one-shot label")
    stale = entries_with_label(c.efi_list(), label)
    if stale:
        return False, f"entry Boot{' '.join(stale)} is labelled {label} already"
    return True, "none"


def _efivarfs_rw(c: _Ctx):
    res = c.ops.findmnt_options(c.efivars_dir)
    opts = res.text.strip()
    if res.rc == 0 and "rw" in opts.split(","):
        return True, f"efivarfs options: {opts}"
    if res.rc != 0 or not opts:
        return False, f"{c.efivars_dir} is not mounted (findmnt rc={res.rc})"
    return False, f"efivarfs not mounted rw, options: {opts}"


def _secure_boot(c: _Ctx):
    found = sorted(glob.glob(os.path.join(c.efivars_dir, "SecureBoot-*")))
    if not found:
        return False, f"no SecureBoot variable under {c.efivars_dir}; Secure Boot state is NOT VERIFIED"
    state = efi.secure_boot_state(found[0])
    if state == "disabled":
        return True, "SecureBoot final byte = 0"
    if state == "unreadable":
        return False, "SecureBoot variable unreadable or has no data byte"
    return False, "SecureBoot enabled (unsigned BOOTAA64.efi, boot.img and DTB would be refused)"


def _images_present(c: _Ctx):
    names = c.manifest_names()
    if not names:
        return False, f"{MANIFEST} lists no checksums"
    absent = []
    for n in names:
        try:
            c.ops.stat_size(f"{c.staging_dir}/{n}")
        except OpFailed:
            absent.append(n)
    if absent:
        return False, f"listed but absent in {c.staging_dir}: {' '.join(absent)}"
    return True, f"{len(names)} image(s) listed in {MANIFEST} are present in {c.staging_dir}"


def _image_checksums(c: _Ctx):
    res = c.ops.sha256sum_check(c.staging_dir, MANIFEST)
    lines = (res.text + res.stderr).splitlines()
    if res.rc != 0 and f"{MANIFEST}: No such file or directory" in res.stderr:
        raise NotExamined(f"{MANIFEST} could not be read: sha256sum: {MANIFEST}: No such file or directory")
    if res.rc == 0:
        n = sum(1 for ln in lines if ln.endswith(": OK"))
        return True, f"sha256sum --strict -c {MANIFEST}: {n} OK"
    bad = ";".join([ln for ln in lines if not ln.endswith(": OK")][:3])
    return False, f"sha256sum --strict -c failed rc={res.rc}: {bad}"


def _staging_space(c: _Ctx):
    need = c.profile.staging.min_free_kib
    avail = c.ops.df_free(c.staging_dir)
    return (
        avail >= need,
        f"{avail} KiB free in {c.staging_dir}, need >= {need} KiB ({need // 1024} MiB) beyond the images",
    )


# name -> (display label, function). The labels follow the kit's wording.
CHECKS: dict[str, tuple[str, Callable]] = {
    "emmc-exists": ("eMMC device exists", _emmc_exists),
    "target-identity": ("target hardware identity", _target_identity),
    "emmc-not-read-only": ("eMMC not read-only", _not_read_only),
    "emmc-sector-count": ("eMMC sector count", _sector_count),
    "emmc-no-partition-table": ("eMMC has no partition table", _no_partition_table),
    "emmc-not-mounted": ("eMMC not mounted", _not_mounted),
    "efibootmgr-supports-create": ("efibootmgr supports -C", _supports_create),
    "boot-order-unchanged": ("BootOrder unchanged", _boot_order),
    "boot-next-unset": ("BootNext unset", _boot_next),
    "no-stale-oneshot-entry": ("no stale {label} entry", _oneshot_label),
    "efivarfs-rw": ("efivarfs mounted read-write", _efivarfs_rw),
    "secure-boot-disabled": ("SecureBoot disabled", _secure_boot),
    "staged-images-present": ("staged images present", _images_present),
    "staged-image-checksums": ("staged image checksums", _image_checksums),
    "staging-space-free": ("staging space free", _staging_space),
}


def _label(c: _Ctx, name: str) -> str:
    entry = CHECKS.get(name)
    if entry is None:
        return name
    label = entry[0]
    if "{label}" in label:
        params = c.profile.arm.params
        label = label.replace("{label}", (params.get("label") if hasattr(params, "get") else None) or "one-shot")
    return label


# -------------------------------------------------------------------- info


def _info_lines(c: _Ctx) -> list:
    out = []

    def attempt(fn, fallback):
        try:
            return fn()
        except _READ_ERRORS as exc:
            return fallback.replace("{why}", str(exc).splitlines()[0][:120] if str(exc) else type(exc).__name__)

    def life():
        base = f"/sys/block/{c.base}/device"
        lt = c.ops.read_file(f"{base}/life_time").decode("utf-8", errors="replace").strip()
        extra = ""
        try:
            eol = c.ops.read_file(f"{base}/pre_eol_info").decode("utf-8", errors="replace").strip()
            extra = f" (pre_eol_info {eol})"
        except _READ_ERRORS:
            pass
        return f"INFO  eMMC life time: {lt}{extra}"

    out.append(attempt(life, "INFO  eMMC life time: unavailable"))

    try:
        out.append(f"INFO  BootCurrent: {c.efi_field('BootCurrent')}")
    except _READ_ERRORS:
        pass

    def fstype():
        fst = c.ops.findmnt_fstype(c.staging_dir).text.strip().splitlines()
        return f"INFO  staging filesystem: {fst[0] if fst else 'unknown'} (tmpfs expected; {c.staging_dir})"

    out.append(attempt(fstype, f"INFO  staging filesystem: unknown (tmpfs expected; {c.staging_dir})"))
    out.append(attempt(lambda: f"INFO  kernel: {c.ops.uname_r()}", "INFO  kernel: unknown"))

    def containers():
        res = c.ops.docker_ps()
        if res.rc != 0:
            return "INFO  running containers: unknown (docker ps failed)"
        n = len([ln for ln in res.text.splitlines() if ln.strip()])
        return f"INFO  running containers: {n} (they stop at reboot)"

    out.append(attempt(containers, "INFO  running containers: unknown ({why})"))
    return out


# --------------------------------------------------------------------- run


def run_check(
    ops: Ops,
    profile,
    *,
    staging_dir,
    efivars_dir=DEFAULT_EFIVARS_DIR,
    expected_boot_order: str | None = None,
    out: Callable = print,
) -> CheckResult:
    """Run every assertion the profile lists; see the module docstring.

    ``expected_boot_order`` is the comma-separated BootOrder the board must
    still have (the profile does not carry one); without it the
    ``boot-order-unchanged`` check is not examined.
    """
    lines: list = []

    def emit(text):
        lines.append(text)
        out(text)

    c = _Ctx(ops, profile, staging_dir, efivars_dir, expected_boot_order)
    names = list(profile.checks)
    total = len(names)
    examined = 0
    failed: list = []
    unexamined: list = []

    emit(HEADER)
    for name in names:
        label = _label(c, name)
        entry = CHECKS.get(name)
        if entry is None:
            emit(f"FAIL  {label}: not examined: no implementation")
            unexamined.append(label)
            continue
        try:
            ok, detail = entry[1](c)
        except NotExamined as exc:
            emit(f"FAIL  {label}: not examined: {exc}")
            unexamined.append(label)
            continue
        except _READ_ERRORS as exc:
            reason = str(exc).splitlines()[0] if str(exc) else type(exc).__name__
            emit(f"FAIL  {label}: not examined: {reason}")
            unexamined.append(label)
            continue
        examined += 1
        if ok:
            emit(f"PASS  {label}: {detail}")
        else:
            emit(f"FAIL  {label}: {detail}")
            failed.append(label)

    for ln in _info_lines(c):
        emit(ln)

    emit(f"checks: {examined}/{total}")
    if failed:
        code = 1
    elif unexamined or total == 0:
        code = 2
    else:
        code = 0
    if code == 0:
        emit("PREFLIGHT PASS")
    else:
        labels = failed + unexamined if total else ["no checks listed"]
        emit("PREFLIGHT FAIL: " + " ".join(f"[{x}]" for x in labels))
    return CheckResult(code, examined, total, lines)
