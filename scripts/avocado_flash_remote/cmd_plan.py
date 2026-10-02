"""The ``plan`` subcommand: look, decide, write one plan record, change nothing.

Everything the plan learns about the board goes through the injected ops
object, which the caller wraps in ``ReadOnlyOps``; this module never imports
subprocess and never touches the filesystem itself. The only write is the plan
record, handed to an injected ``record_writer`` (default: the evidence
module's atomic writer into the run directory).

Output keeps the section structure and wording of the bash kit's dry run
(``tests/remote/golden/real-board-dry-run.txt``). Lines this tool adds sit in
a header block that ends at ``BODY_MARKER``; everything after the marker is
the kit-comparable body.

Standard library only (ships to a board running Python 3.10).
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import posixpath
import re
from dataclasses import dataclass, field
from typing import Callable

from . import arm as armmod
from . import evidence, images, layout
from .ops import Ops, OpsError

SCHEMA_VERSION = 1
RECORD_NAME = "plan.json"
BODY_MARKER = "== plan =="
DONE_LINE = "dry run complete: no mutating tool was called"
UNAVAILABLE = "unavailable"
# The sha256sum-format file the host stages (the bash kit calls it MANIFEST).
# Same value as cmd_check.MANIFEST; kept local so plan does not import check.
MANIFEST_NAME = "MANIFEST.hashes"
# Kit install.sh prints this in the section title; it names the design doc
# the layout was validated against.
_LAYOUT_REF = "boot-design.md section 1"

_DEVICE_RE = re.compile(r"^/dev/(?:mmcblk[0-9]+|sd[a-z]+|vd[a-z]+)$")
_SUM_RE = re.compile(r"^([0-9a-fA-F]{64})[ \t][ *](.+)$")
_NO_TABLE_RE = re.compile(r"recognized partition table|no partition table", re.I)
_SAFE_RE = re.compile(r"^[A-Za-z0-9_@%+=:,./-]+$")


class _Refusal(Exception):
    pass


@dataclass
class PlanResult:
    exit_code: int
    plan_record: dict | None
    lines: list = field(default_factory=list)


def _q(arg: str) -> str:
    """Quote like bash printf %q, which the kit's dry run uses."""
    if arg and _SAFE_RE.match(arg):
        return arg
    return "".join(c if _SAFE_RE.match(c) else "\\" + c for c in arg)


def _utc_now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _read_text(ops: Ops, path: str) -> str | None:
    try:
        return ops.read_file(path).decode("utf-8", errors="replace").strip()
    except (OSError, OpsError):
        return None


# ------------------------------------------------------------------ checks


def _check_device(device: str) -> None:
    if "nvme" in device:
        raise _Refusal(f"refusing {device}: this tool never touches an NVMe device")
    if not _DEVICE_RE.match(device):
        raise _Refusal(f"refusing {device}: not a whole eMMC/SD/virtio disk node")


def _check_sectors(ops: Ops, profile) -> None:
    dev = profile.target.device
    got = ops.blockdev_getsz(dev)
    if got != profile.target.sectors:
        raise _Refusal(f"{dev} has {got} sectors, expected {profile.target.sectors}")


# Deepest stack (partition -> dm -> dm -> md ...) the walk follows before it gives up and refuses.
MAX_STACK_DEPTH = 8
_SYS_BLOCK = "/sys/class/block"
_SUBVOL_RE = re.compile(r"\[[^\]]*\]$")


def _resolve_name(ops: Ops, node: str, what: str) -> str:
    """Kernel name behind a /dev node, following every symlink (/dev/root, by-uuid, /dev/mapper)."""
    try:
        real = ops.realpath(node)
    except (OSError, OpsError) as exc:
        raise _Refusal(f"cannot resolve {what} {node} to a device ({type(exc).__name__}); refusing") from None
    if not real.startswith("/dev/") or real == "/dev/":
        raise _Refusal(f"cannot resolve {what} {node}: it resolves to {real}, not a device node; refusing")
    return posixpath.basename(real)


def _is_partition(ops: Ops, name: str) -> bool:
    try:
        ops.read_file(f"{_SYS_BLOCK}/{name}/partition")
    except FileNotFoundError:
        return False
    except (OSError, OpsError) as exc:
        raise _Refusal(f"cannot resolve {name}: sysfs partition attribute unreadable ({type(exc).__name__}); refusing") from None
    return True


def _loop_backing_file(ops: Ops, name: str) -> str | None:
    """Path of the file behind loop device ``name``; None when it has no backing_file attribute (not a loop, or unconfigured).

    An attribute that is unreadable, empty or marked deleted refuses: the file's filesystem cannot be probed,
    so the device cannot be shown to be off the target.
    """
    try:
        raw = ops.read_file(f"{_SYS_BLOCK}/{name}/loop/backing_file")
    except FileNotFoundError:
        return None
    except (OSError, OpsError) as exc:
        raise _Refusal(f"cannot resolve loop device {name}: backing file unreadable ({type(exc).__name__}); refusing") from None
    path = raw.decode("utf-8", errors="replace").strip()
    if not path.startswith("/"):
        raise _Refusal(f"cannot resolve loop device {name}: backing file {path!r} is empty or not an absolute path; refusing")
    if path.endswith(" (deleted)"):
        raise _Refusal(f"cannot resolve loop device {name}: its backing file {path} is deleted; refusing")
    return path


def _ancestors(ops: Ops, name: str, depth: int, seen: set, target_name: str) -> set:
    """Kernel names of ``name`` and everything it is built on: parent disk of a partition, slaves of dm/md, and for
    a loop device the device behind its backing file (which adds ``target_name`` when that file sits on the target)."""
    if name in seen:
        return set()
    if depth > MAX_STACK_DEPTH:
        raise _Refusal(f"device stack under {name} is deeper than {MAX_STACK_DEPTH} levels; refusing")
    seen.add(name)
    found = {name}
    try:
        sysnode = ops.realpath(f"{_SYS_BLOCK}/{name}")
    except (OSError, OpsError) as exc:
        raise _Refusal(f"cannot resolve {name}: no sysfs entry ({type(exc).__name__}); refusing") from None
    if _is_partition(ops, name):
        return found | _ancestors(ops, posixpath.basename(posixpath.dirname(sysnode)), depth + 1, seen, target_name)
    try:
        slaves = ops.listdir(f"{_SYS_BLOCK}/{name}/slaves")
    except (OSError, OpsError) as exc:
        raise _Refusal(f"cannot resolve {name}: slaves unreadable ({type(exc).__name__}); refusing") from None
    for slave in slaves:
        found |= _ancestors(ops, slave, depth + 1, seen, target_name)
    backing = _loop_backing_file(ops, name)
    if backing is not None and _path_backs_target(ops, f"backing file of loop device {name}", backing, target_name, depth + 1):
        found.add(target_name)
    return found


def _backs_target(ops: Ops, source: str, target_name: str, what: str, depth: int = 0) -> bool:
    return target_name in _ancestors(ops, _resolve_name(ops, source, what), depth, set(), target_name)


# Sources the kernel serves from RAM or itself; nothing on a block device can sit behind them.
_KERNEL_SOURCES = frozenset({
    "tmpfs", "ramfs", "devtmpfs", "proc", "sysfs", "cgroup", "cgroup2", "devpts", "securityfs", "debugfs",
    "tracefs", "configfs", "pstore", "mqueue", "hugetlbfs", "bpf", "fusectl", "binfmt_misc", "autofs",
    "efivarfs", "selinuxfs",
})  # fmt: skip


def _findmnt_one(ops: Ops, what: str, column: str, path: str) -> str:
    res = ops.run_read(["findmnt", "-no", column, "-T", path], check=False)
    lines = [ln for ln in res.text.splitlines() if ln.strip()]
    if res.rc != 0 or len(lines) != 1:
        why = f"rc={res.rc}" if res.rc != 0 else ("no output" if not lines else "more than one value")
        raise _Refusal(f"cannot tell what backs the {what}: findmnt {column} probe for {path} failed ({why}); refusing")
    return lines[0].strip()


def _overlay_dirs(options: str, path: str, what: str) -> list:
    """lowerdir entries, then upperdir and workdir, from an overlay mount's options; refuses what it cannot read."""
    lower: list = []
    upper = work = None
    for opt in options.split(","):
        key, _, val = opt.partition("=")
        if key == "lowerdir":
            lower = val.split(":")
        elif key == "upperdir":
            upper = val
        elif key == "workdir":
            work = val
    extra = [d for d in (upper, work) if d is not None]
    if (upper is None) != (work is None) or not lower or any(not d.startswith("/") for d in lower + extra):
        raise _Refusal(
            f"cannot tell what backs the {what}: overlay options of {path} are missing or unparseable "
            f"(need lowerdir, and upperdir with workdir); refusing"
        )
    return lower + extra


def _path_backs_target(ops: Ops, what: str, path: str, target_name: str, depth: int = 0) -> str | None:
    """Name of the block device that is or sits under the target and backs ``path``, else None.

    A block-device source is walked through sysfs. An overlay is followed into every lower, upper and work
    directory with the same probe, so a stack on the target cannot hide behind the overlay's own name.
    A source that is none of these (nfs, fuse, ecryptfs and the like) cannot be shown to be off the target,
    so it refuses.
    """
    if depth > MAX_STACK_DEPTH:
        raise _Refusal(f"overlay stack under the {what} is deeper than {MAX_STACK_DEPTH} levels; refusing")
    source = _SUBVOL_RE.sub("", _findmnt_one(ops, what, "SOURCE", path))
    if source.startswith("/"):
        return source if _backs_target(ops, source, target_name, what, depth) else None
    if source in _KERNEL_SOURCES:
        return None
    fstype = _findmnt_one(ops, what, "FSTYPE", path)
    if fstype != "overlay":
        if fstype in _KERNEL_SOURCES:
            return None
        raise _Refusal(
            f"cannot tell what backs the {what}: {path} is on a {fstype!r} filesystem that is not a block "
            "device, an overlay or a kernel/RAM filesystem; refusing"
        )
    for directory in _overlay_dirs(_findmnt_one(ops, what, "OPTIONS", path), path, what):
        hit = _path_backs_target(ops, what, directory, target_name, depth + 1)
        if hit is not None:
            return hit
    return None


def _check_not_in_use(ops: Ops, profile, staging_dir: str) -> None:
    dev = profile.target.device
    target_name = _resolve_name(ops, dev, "target")
    for what, path in (
        ("running root", "/"),
        ("staging directory", staging_dir),
        ("SSH path", "/etc/ssh"),
    ):
        source = _path_backs_target(ops, what, path, target_name)
        if source is not None:
            raise _Refusal(f"{dev} backs the {what} ({path} is on {source}); refusing")
    for source in ops.findmnt_source():
        source = _SUBVOL_RE.sub("", source.strip())
        if source.startswith("/dev/") and _backs_target(ops, source, target_name, "mounted source"):
            raise _Refusal(f"{dev} or one of its partitions is mounted ({source})")


def _check_empty(ops: Ops, profile) -> None:
    dev = profile.target.device
    name = posixpath.basename(dev)
    out = ops.lsblk(dev, "NAME,TYPE", check=True).text
    parts = [ln for ln in out.splitlines() if len(ln.split()) >= 2 and ln.split()[1] == "part"]
    if parts:
        raise _Refusal(f"lsblk shows {len(parts)} partition(s) on {dev}; refusing a disk that is not empty")
    res = ops.sfdisk_dump(dev, check=False)
    if res.rc != 0:
        if _NO_TABLE_RE.search(res.stderr):
            return
        raise _Refusal(f"sfdisk --dump {dev} failed (rc={res.rc}): {res.stderr.strip()[:200]}")
    if any(ln.startswith(("label:", "label-id:")) or ln.startswith(dev) for ln in res.text.splitlines()):
        raise _Refusal(f"{dev} already carries a partition table; refusing ({name})")


def _resolve_identity(ops: Ops, profile) -> tuple[str, str]:
    """Apply the profile identity constraint; return (verified value, device serial)."""
    dev = profile.target.device
    name = posixpath.basename(dev)
    ident = profile.target.identity
    serial_path = f"/sys/block/{name}/device/serial"
    serial = _read_text(ops, serial_path) or UNAVAILABLE
    if ident.kind == "sysfs-name":
        if name != ident.value:
            raise _Refusal(f"device identity mismatch: {dev} is sysfs name {name}, profile expects {ident.value}")
        return name, serial
    if ident.kind == "serial":
        attr = ident.sysfs_attr or "serial"
        got = _read_text(ops, f"/sys/block/{name}/device/{attr}")
        if got is None:
            raise _Refusal(f"device identity cannot be verified: /sys/block/{name}/device/{attr} is unreadable")
        if got != ident.value:
            raise _Refusal(f"device identity mismatch: serial {got!r}, profile expects {ident.value!r}")
        return got, got
    return _resolve_by_path(ops, dev, ident.value), serial


def _resolve_by_path(ops: Ops, dev: str, value: str) -> str:
    """The by-path link must resolve to the very device the profile names; absence or a mismatch refuses."""
    if not value or "/" in value or value in (".", ".."):
        raise _Refusal(f"device identity cannot be verified: by-path value {value!r} is not a bare link name")
    link = f"/dev/disk/by-path/{value}"
    try:
        got = _resolve_name(ops, link, "by-path identity")
    except _Refusal as exc:
        raise _Refusal(f"device identity cannot be verified: {exc}") from None
    want = _resolve_name(ops, dev, "target")
    if got != want:
        raise _Refusal(f"device identity mismatch: {link} resolves to {got}, the target is {want}")
    return value


def _parse_manifest(text: str) -> dict:
    out = {}
    for line in text.splitlines():
        m = _SUM_RE.match(line.rstrip("\r"))
        if m:
            path = m.group(2)
            out[path[2:] if path.startswith("./") else path] = m.group(1).lower()
    return out


def check_image_limits(profile, scans: dict) -> None:
    """Size, populated and partition-capacity limits for every image; write re-applies them to its own scans."""
    parts = {p["number"]: p for p in profile.layout.params["table"]}
    sector = profile.layout.params.get("sector_size", 512)
    for role, img in profile.images.items():
        scan = scans[img.file]
        if scan.size > img.max_bytes:
            raise _Refusal(f"image {role} {img.file} is {scan.size} bytes, limit {img.max_bytes}")
        if img.must_be_populated and scan.all_zero:
            raise _Refusal(f"image {role} {img.file} is all zero ({scan.size} bytes) but must be populated")
        cap = parts[img.partition]["size"] * sector
        if scan.size > cap:
            raise _Refusal(
                f"image {role} {img.file} is {scan.size} bytes, larger than partition "
                f"{parts[img.partition]['name']} ({cap} bytes)"
            )


def _check_images(ops: Ops, profile, staging_dir: str, scanner) -> tuple[dict, int]:
    manifest_path = f"{staging_dir}/{MANIFEST_NAME}"
    try:
        raw = ops.read_file(manifest_path)
    except (OSError, OpsError) as exc:
        raise _Refusal(f"manifest not found: {manifest_path} ({exc})") from exc
    manifest = _parse_manifest(raw.decode("utf-8", errors="replace"))
    if not manifest:
        raise _Refusal(f"manifest {manifest_path} lists no sha256 checksums")
    scans: dict = {}
    for role, img in profile.images.items():
        if img.file not in manifest:
            raise _Refusal(f"{role} image '{img.file}' has no checksum in {manifest_path}")
    for role, img in profile.images.items():
        if img.file in scans:
            continue
        try:
            scans[img.file] = scanner(f"{staging_dir}/{img.file}")
        except OSError:
            raise _Refusal(f"staged image {role} {img.file} not found in {staging_dir}") from None
        if scans[img.file].sha256 != manifest[img.file]:
            raise _Refusal(f"checksum verification failed for {img.file} ({role}); nothing was written")
    check_image_limits(profile, scans)
    return scans, len(manifest)


# -------------------------------------------------------------- rendering


def _next_text(entry_number: str) -> str:
    return " ".join(_q(a) for a in Ops.vec_efibootmgr_next(entry_number))


def _body(profile, staging_dir: str, sfdisk_text: str, n_manifest: int, entry_number: str = "") -> list:
    dev = profile.target.device
    params = profile.layout.params
    ordered = sorted(params["table"], key=lambda p: (p["start"], p["number"]))
    name_of = {p["number"]: p["name"] for p in params["table"]}
    node_of_name = {p["name"]: layout.partition_node(dev, p["number"]) for p in params["table"]}
    lines = [
        f"verifying checksums from {staging_dir}/{MANIFEST_NAME}",
        f"checksums OK ({n_manifest} file(s))",
        f"== partitions to create on {dev} ({_LAYOUT_REF}) ==",
    ]
    for p in ordered:
        node = layout.partition_node(dev, p["number"])
        lines.append(
            f"  {node:<16} {p['name']:<20} start={p['start']:<8} size={p['size']:<10} type={p['type_guid']}"
        )
    lines.append("== images to write ==")
    writes = []
    for img in profile.images.values():
        node = layout.partition_node(dev, img.partition)
        writes.append((img, node))
        lines.append(f"  {img.file} -> {node} ({name_of[img.partition]})")

    arm_params = profile.arm.params
    esp = profile.images.get("esp")
    arming = profile.arm.strategy == "uefi-bootnext" and esp is not None
    if arming:
        lines += [
            "== boot entry (BootNext only, BootOrder untouched) ==",
            f"  select : the firmware's existing entry {arm_params['entry_label']!r} (Boot{entry_number}); "
            "no entry is created or deleted",
            f"  arm    : {_next_text(entry_number)}",
        ]
    lines += ["== dry run ==", "  would create the table from this sfdisk input:"]
    lines += ["    " + ln for ln in sfdisk_text.splitlines()]
    lines.append("DRY-RUN would run: " + " ".join(_q(a) for a in Ops.vec_sfdisk_write(dev)))
    for img, node in writes:
        vec = Ops.vec_dd_write(f"{staging_dir}/{img.file}", node)
        lines.append("DRY-RUN would run: " + " ".join(_q(a) for a in vec))
    if profile.guard.strategy == "boot-arg":
        nodes = [node_of_name[n] for n in profile.guard.params["partitions"]]
        lines.append(
            f"DRY-RUN would read back the boot image header from {' and '.join(nodes)} "
            "and refuse BootNext unless the NVMe-hiding argument is present"
        )
    if arming:
        lines.append(f"DRY-RUN would run: {_next_text(entry_number)}")
    lines.append(DONE_LINE)
    return lines


# -------------------------------------------------------------------- run


def run_plan(
    ops: Ops,
    profile,
    profile_hash: str,
    *,
    staging_dir: str,
    run_dir: str,
    record_writer: Callable | None = None,
    board_identity: dict | None = None,
    run_id: str,
    out: Callable = print,
    scanner: Callable = images.scan,
    now: Callable = _utc_now,
    file_reader: Callable | None = None,
) -> PlanResult:
    """Verify, decide and write the plan record. Mutates nothing on the board."""
    writer = record_writer or evidence.write_record
    try:
        _check_device(profile.target.device)
        _check_sectors(ops, profile)
        _check_not_in_use(ops, profile, staging_dir)
        _, serial = _resolve_identity(ops, profile)
        if profile.target.require_empty:
            _check_empty(ops, profile)
        try:
            layout.check_fits(profile.layout.params, profile.target.sectors)
            sfdisk_text = layout.sfdisk_input(profile.layout.params, profile.target.device)
        except layout.LayoutError as exc:
            raise _Refusal(f"layout does not fit the target: {exc}") from exc
        scans, n_manifest = _check_images(ops, profile, staging_dir, scanner)
        try:
            armmod.get_guard(profile.guard.strategy).check_staged(profile, staging_dir, file_reader)
        except armmod.GuardError as exc:
            raise _Refusal(str(exc)) from exc
        try:
            record = armmod.get_arm(profile.arm.strategy).prepare(ops, profile)
        except armmod.ArmError as exc:
            raise _Refusal(f"arm pre-flight refused: {exc}") from exc

        if board_identity is None:
            board_identity = {
                "machine_id": _read_text(ops, "/etc/machine-id") or UNAVAILABLE,
                "device_serial": serial,
            }
        arm_summary = dict(record.to_dict(), strategy=profile.arm.strategy)
        plan_record = {
            "schema_version": SCHEMA_VERSION,
            "run_id": run_id,
            "profile_hash": profile_hash,
            "board_identity": board_identity,
            "device": profile.target.device,
            "image_hashes": {r: scans[i.file].sha256 for r, i in profile.images.items()},
            "image_sizes": {r: scans[i.file].size for r, i in profile.images.items()},
            "table_hash": hashlib.sha256(sfdisk_text.encode()).hexdigest(),
            "arm": arm_summary,
            "created_utc": now(),  # evidence only; never compared or branched on
        }
        try:
            writer(run_dir, RECORD_NAME, plan_record)
        except OSError as exc:
            raise _Refusal(f"cannot write the plan record: {exc}") from exc
    except _Refusal as exc:
        lines = [f"plan refused: {exc}"]
        for ln in lines:
            out(ln)
        return PlanResult(1, None, lines)

    ident = profile.target.identity
    header = [
        "== plan header (added by this tool) ==",
        f"profile: {profile.board} sha256={profile_hash}",
        f"device identity: {profile.target.device} kind={ident.kind} value={ident.value} "
        f"serial={board_identity.get('device_serial', UNAVAILABLE)}",
        f"board identity: machine-id={board_identity.get('machine_id', UNAVAILABLE)}",
        f"run id: {run_id}",
        f"plan record: {run_dir}/{RECORD_NAME}",
        BODY_MARKER,
    ]
    lines = header + _body(profile, staging_dir, sfdisk_text, n_manifest, record.entry_number)
    for ln in lines:
        out(ln)
    return PlanResult(0, plan_record, lines)
