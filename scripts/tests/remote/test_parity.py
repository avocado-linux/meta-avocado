"""Differential parity suite: the port against the bash kit's golden call log.

This is the parity gate. ``golden/calls.log`` holds, per case, the exit code
and the tool-call log the kit's own fixtures recorded (87 cases). Here every
install and window case is replayed against the port's ``Recording`` ops with
the same fixtures, and the recorded calls and exit codes are compared with the
golden. The suite only ever READS the golden files; it never rewrites or
regenerates one (see ``golden/README.md``) and a missing listed case fails it.

Every install and window case carries an explicit verdict in ``CASES``:

``EXACT``    the port's call sequence, after the normalisations below, equals
             the golden lines and the exit code is equal.
``OUTCOME``  same refusal or success class. Exit code equal (or, where noted,
             same zero / non-zero class); a refusal makes zero mutating calls;
             a success makes the same mutating-call SEQUENCE as the kit. With
             ``reads`` set, the kit's read calls must also appear, in order, in
             the port's calls.
``DIFFERS``  a documented deliberate difference. The check asserts the port
             behaves as the documented alternative AND that the golden still
             shows the kit's behaviour. ``DIFFERENCES`` explains each.
``NA``       the port has no equivalent; the reason is recorded.

The 24 ``stage:`` cases concern the kit's ``stage.sh``, which the port replaces
with ``host.stage`` (a tar stream over one ssh with different mechanics), so
only OUTCOME parity is asserted for those; ``STAGE_TABLE`` maps each one.

Normalisation of the port's recorded lines (the golden is already normalised
by ``golden/capture-notes.md``): the staged image paths become
``<TMP>/images/<kit file name>``, the staging directory ``<TMP>/stage``, the
efivars directory ``/sys/firmware/efi/efivars``. Mutating calls are classified
by ``is_mut`` below, applied to both sides.

Standard library only; no network, no subprocess.
"""

from __future__ import annotations

import hashlib
import json
import pathlib
import re
from collections import namedtuple
from dataclasses import dataclass, field
from types import SimpleNamespace as NS

import pytest

import test_cmd_check as tcc
import test_cmd_plan as tcp
import test_cmd_readback_status as tcrb
import test_cmd_write as tcw
from avocado_flash_remote import bundle, host, runner
from avocado_flash_remote import state as statemod
from avocado_flash_remote.arm import ArmRecord
from avocado_flash_remote.cmd_check import run_check
from avocado_flash_remote.cmd_readback import run_readback
from avocado_flash_remote.cmd_restore import NOTE_LINE, run_restore
from avocado_flash_remote.host import HostError, RunResult, StubTransport
from avocado_flash_remote.images import ScanResult
from avocado_flash_remote.ops import OpFailed, OpResult, ReadOnlyOps, RecordingOps
from avocado_flash_remote.profile import ProfileError, load_profile_bytes

HERE = pathlib.Path(__file__).resolve().parent
GOLDEN_DIR = HERE / "golden"
CALLS_LOG = GOLDEN_DIR / "calls.log"
DRY_RUN = GOLDEN_DIR / "real-board-dry-run.txt"
PROFILES = HERE.parent.parent / "avocado_flash_remote" / "profiles"
SHIPPED = PROFILES / "jetson-agx-orin-j5012.json"
FIXTURE_NONE = PROFILES / "fixture-none.json"

DEV = "/dev/mmcblk0"
STAGE = "/run/emmc-test-images"
EFIVARS_REAL = "/sys/firmware/efi/efivars"
LABEL = tcw.LABEL

# ------------------------------------------------------------ the case lists

INSTALL_NAMES = [
    "install:dry", "install:dry#2", "install:ok", "install:ok#2", "install:ok#3",
    "install:ok#4", "install:ok#5", "install:rmismatch1", "install:rmismatch1#2",
    "install:rmismatch2", "install:rmismatch2#2", "install:rnostate",
    "install:disk-nvme0n1", "install:disk-nvme0n1p1", "install:disk-sda",
    "install:disk-nvme-dry", "install:badsum", "install:modified", "install:foreign",
    "install:foreign-lsblk", "install:mounted", "install:badcmd", "install:unseated",
    "install:readback", "install:extracmd", "install:nearmiss", "install:hdrv3",
    "install:noarg", "install:bochange", "install:noc", "install:nocfb",
    "install:devimages", "install:nondevimages",
]  # fmt: skip
WINDOW_NAMES = [
    "window:pf-good", "window:pf-parttable", "window:pf-sectors", "window:pf-readonly",
    "window:pf-mounted", "window:pf-bootnext", "window:pf-bootorder", "window:pf-stale",
    "window:pf-noC", "window:pf-efivarfsro", "window:pf-secureboot", "window:pf-corrupt",
    "window:pf-space", "window:pf-sb-absent", "window:pf-image-missing",
    "window:pf-missing-tool", "window:pf-no-manifest", "window:pf-efi-fail",
    "window:pf-noroot", "window:rb-default", "window:rb-entry", "window:rb-fallback",
    "window:rb-differs", "window:rb-notmpfs", "window:rb-mountfail", "window:rb-missing-tool",
    "window:rb-cleanup", "window:rb-cleanup-two", "window:rb-cleanup-none",
    "window:rb-cleanup-next-only",
]  # fmt: skip
STAGE_NAMES = [
    "stage:dry", "stage:defsrc", "stage:oldsrc", "stage:dev-_dev_shm_x", "stage:dev-_dev_shm",
    "stage:dev-_dev", "stage:dev-_dev_mmcblk0p1", "stage:dev-_dev_.._run_x", "stage:devmsg",
    "stage:out-_tmp_x", "stage:out-_home_user_x", "stage:out-_etc", "stage:out-_runx_y",
    "stage:out-_run", "stage:out-_var_tmp", "stage:out-_run_.._etc_x", "stage:ok",
    "stage:custom", "stage:corrupt", "stage:corrupt-install.sh", "stage:corrupt-preflight.sh",
    "stage:corrupt-readback.sh", "stage:sshfail", "stage:badsrc",
]  # fmt: skip
ALL_NAMES = INSTALL_NAMES + STAGE_NAMES + WINDOW_NAMES  # the order calls.log records them

# ------------------------------------------------------------------ golden


@dataclass
class Golden:
    name: str
    exit: int
    lines: list = field(default_factory=list)

    @property
    def muts(self) -> list:
        return [ln for ln in self.lines if is_mut(ln)]

    @property
    def kit_reads(self) -> list:
        """Read calls the kit made, minus the scratch-file header reads the
        kit does with ``dd ... of=<file>`` (the port reads the header straight
        from the partition)."""
        return [ln for ln in self.lines if "bhdr." not in ln and not is_mut(ln)]


def parse_golden(text: str) -> dict:
    cases: dict = {}
    cur = None
    for ln in text.splitlines():
        if ln.startswith("=== CASE "):
            name = ln[len("=== CASE "):]
            assert name not in cases, f"duplicate golden case {name}"
            cur = cases[name] = Golden(name, -1)
        elif cur is not None and cur.exit == -1 and ln.startswith("exit="):
            cur.exit = int(ln[5:])
        elif cur is not None:
            cur.lines.append(ln)
    return cases


_READ_SFDISK = {"--dump", "-d", "-l", "--list", "-F", "--list-free", "-J", "--json", "-V"}
_MUT_TOOLS = {"wipefs", "mount", "umount", "udevadm", "parted", "sgdisk", "partprobe", "blkdiscard"}


def is_mut(line: str) -> bool:
    """Mutating-call classifier, applied identically to golden and port lines.

    Follows the kit's own ``is_mut`` (test-install.sh) and also counts
    ``udevadm settle``, which is part of the mutating sequence.
    """
    tok = line.split()
    if not tok:
        return False
    tool, args = tok[0], tok[1:]
    if tool == "sfdisk":
        return not (set(args) & _READ_SFDISK)
    if tool == "dd":
        return any(a.startswith("of=/dev/") and a != "of=/dev/null" for a in args)
    if tool == "efibootmgr":
        return not set(args) <= {"-v", "--help"}
    if tool == "blockdev":
        return not (set(args) & {"--getsz", "--getsize64", "--getro"})
    return tool in _MUT_TOOLS or tool.startswith("mkfs")


def _read_golden() -> dict:
    return parse_golden(CALLS_LOG.read_text())


def _golden_digests() -> dict:
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(GOLDEN_DIR.iterdir()) if p.is_file()}


_DIGESTS_AT_IMPORT = _golden_digests()


@pytest.fixture(scope="module", autouse=True)
def golden_untouched():
    yield
    assert _golden_digests() == _DIGESTS_AT_IMPORT, "a golden file changed while the parity suite ran"


@pytest.fixture(scope="module")
def golden() -> dict:
    return _read_golden()


# ----------------------------------------------------------------- port run


@dataclass
class PortRun:
    exit: int
    lines: list = field(default_factory=list)  # normalised recorded exec calls
    out: list = field(default_factory=list)  # what the subcommand printed
    raised: BaseException | None = None
    extra: dict = field(default_factory=dict)

    @property
    def muts(self) -> list:
        return [ln for ln in self.lines if is_mut(ln)]

    @property
    def text(self) -> str:
        return "\n".join(self.out)


KIT_NAMES = {
    "boot": "boot.img",
    "boot_b": "boot.img",
    "dtb": "board.dtb",
    "dtb_b": "board.dtb",
    "esp": "esp.img",
    "rootfs": "rootfs.erofs-lz4",
    "var": "var.btrfs",
}


def normaliser(profile, stage=STAGE, efivars=None):
    pairs = [(f"{stage}/{img.file}", f"<TMP>/images/{KIT_NAMES[role]}") for role, img in profile.images.items()]
    pairs.append((stage, "<TMP>/stage"))
    if efivars is not None:
        pairs.append((str(efivars), EFIVARS_REAL))

    def norm(line: str) -> str:
        for old, new in pairs:
            line = line.replace(old, new)
        return line

    return norm


def exec_lines(ops: RecordingOps, norm) -> list:
    return [norm(c.line) for c in ops.calls if c.kind == "exec"]


def shipped_profile():
    return load_profile_bytes(SHIPPED.read_bytes())


# ------------------------------------------------------------ port scenarios
# Each scenario takes a fresh tmp directory and returns a PortRun. They mirror
# the fixtures of the kit's test scripts (test-install.sh, test-window-scripts.sh).


def _write(tmp, *, profile_bytes=tcw.SHIPPED_BYTES, over=None, env_tweak=None, **run_kw):
    env = tcw.Env(tmp, profile_bytes)
    if env_tweak:
        env_tweak(env)
    script = env.script(**(over(env) if over else {}))
    ops = RecordingOps(script)
    res, _ = env.run(ops, **run_kw)
    norm = normaliser(env.profile, efivars=env.efivars)
    return PortRun(res.exit_code, exec_lines(ops, norm), res.lines, extra={"env": env, "res": res, "ops": ops})


def s_install_ok(tmp):
    return _write(tmp)


def _plan(tmp, *, profile_bytes=None, scans=None, scanner=None, **script_kw):
    if profile_bytes is None:
        profile, phash = tcp.load()
    else:
        profile, phash = tcp.load(profile_bytes)
    scans = scans if scans is not None else tcp.scans_for(profile)
    inner = RecordingOps(tcp.script_for(profile, scans, **script_kw))
    res, _, rec = tcp.plan(profile, phash, scans=scans, ops=ReadOnlyOps(inner), scanner=scanner)
    norm = normaliser(profile)
    return PortRun(res.exit_code, exec_lines(inner, norm), res.lines, extra={"records": rec.calls, "ops": inner})


FOREIGN_DUMP = OpResult(
    stdout=b"label: gpt\nlabel-id: 11111111-2222-3333-4444-555555555555\ndevice: /dev/mmcblk0\n"
    b"/dev/mmcblk0p1 : start=2048, size=2048, type=0FC63DAF-8483-4772-8E79-3D69D8477DE4\n"
)


def s_dry(tmp):
    return _plan(tmp)


def s_ok2(tmp):
    """A second install after the first: the disk now carries the written table."""
    return _plan(tmp, sfdisk=FOREIGN_DUMP)


def s_foreign(tmp):
    return _plan(tmp, sfdisk=FOREIGN_DUMP)


def s_foreign_lsblk(tmp):
    return _plan(tmp, lsblk="mmcblk0 disk\nmmcblk0p1 part\n")


def s_mounted(tmp):
    return _plan(tmp, mounted="/dev/nvme0n1p1\n/dev/mmcblk0p11\n")


def s_badsum(tmp):
    profile, _ = tcp.load()
    scans = tcp.scans_for(profile)
    rootfs = profile.images["rootfs"].file
    flipped = "".join(
        (("0" if s.sha256[0] != "0" else "1") + s.sha256[1:] if name == rootfs else s.sha256) + f"  {name}\n"
        for name, s in scans.items()
    )
    return _plan(tmp, scans=scans, manifest=flipped)


def s_modified(tmp):
    profile, _ = tcp.load()
    scans = tcp.scans_for(profile)
    var = profile.images["var"].file

    def scanner(path):
        name = path.rsplit("/", 1)[-1]
        s = scans[name]
        if name == var:  # one byte appended after the manifest was made
            return ScanResult(s.size + 1, tcp.sha("x" + s.sha256), False, s.identity)
        return s

    return _plan(tmp, scans=scans, scanner=scanner)


def _disk_profile_bytes(device):
    doc = json.loads(SHIPPED.read_bytes())
    doc["target"]["device"] = device
    return json.dumps(doc).encode()


def _disk(device):
    def scenario(tmp):
        return _plan(tmp, profile_bytes=_disk_profile_bytes(device))

    return scenario


def s_devimages(tmp):
    doc = json.loads(SHIPPED.read_bytes())
    doc["staging"]["dir"] = "/dev/shm/emmc-test-images"
    try:
        load_profile_bytes(json.dumps(doc).encode())
    except ProfileError as exc:
        return PortRun(runner.EXIT_PROFILE, [], [str(exc)], raised=exc)
    raise AssertionError("a staging directory under /dev was accepted")


def _nvme_arg_header(arg, *, version=0, in_extra=False):
    hdr = bytearray(2048)
    hdr[0:8] = b"ANDROID!"
    hdr[40:44] = version.to_bytes(4, "little")
    if in_extra:
        cmd, extra = b"console=ttyTCU0,115200", f"{arg} quiet".encode()
    else:
        cmd, extra = f"console=ttyTCU0,115200 {arg} quiet".encode(), b""
    hdr[64 : 64 + len(cmd)] = cmd
    hdr[608 : 608 + len(extra)] = extra
    return bytes(hdr)


def _guard_over(header):
    return lambda env: {env.guard_key("A_kernel"): header, env.guard_key("B_kernel"): header}


def _staged_bad(header):
    """The bad header is the STAGED boot.img, injected through file_reader."""
    return lambda tmp: _write(tmp, file_reader=lambda path: header if path.endswith("boot.img") else tcw.boot_header())


s_badcmd = _staged_bad(tcw.boot_header("quiet"))
s_nearmiss = _staged_bad(tcw.boot_header(tcw.NVME_ARG + "_x"))
s_hdrv3 = _staged_bad(_nvme_arg_header(tcw.NVME_ARG, version=3))
s_noarg = _staged_bad(tcw.boot_header("quiet"))  # the kit's manifest lacked the argument: no source of it


def s_readback(tmp):
    """The source boot image was fine; the cmdline read back from the partition is not."""
    return _write(tmp, over=_guard_over(tcw.boot_header("quiet")))


def s_extracmd(tmp):
    return _write(tmp, over=_guard_over(_nvme_arg_header(tcw.NVME_ARG, in_extra=True)))


def s_unseated(tmp):
    """The kit's --nvme-unseated: the profile that opts out of the guard."""
    doc = json.loads(tcw.SHIPPED_BYTES)
    doc["guard"] = {"strategy": "none", "params": {}}
    return _write(tmp, profile_bytes=json.dumps(doc).encode(), over=_guard_over(tcw.boot_header("quiet")))


def s_bochange(tmp):
    def over(env):
        changed = tcw.EFI_AFTER.replace(f"BootOrder: {tcw.ORDER}", f"BootOrder: {tcw.ENTRY},{tcw.ORDER}")
        return {"efibootmgr -v": [tcw.EFI_PRE, tcw.EFI_PRE, tcw.EFI_PRE, changed, tcw.EFI_FINAL]}

    return _write(tmp, over=over)


def s_noc(tmp):
    return _write(tmp, over=lambda env: {"efibootmgr --help": "Usage: efibootmgr [-c]\n  -c | --create\n"})


# ---- window: preflight


def _efivars(tmp, secure_boot=0):
    d = tmp / "efivars"
    d.mkdir(exist_ok=True)
    if secure_boot is not None:
        (d / "SecureBoot-8be4df61-93ca-11d2-aa0d-00e098032b8c").write_bytes(bytes([7, 0, 0, 0, secure_boot]))
    return d


def _pf(tmp, *, secure_boot=0, over=None):
    efivars = _efivars(tmp, secure_boot)
    over = over(efivars) if callable(over) else (over or {})
    ops = RecordingOps(tcc.script(efivars, **over))
    profile = tcc.shipped()
    lines = []
    res = run_check(
        ReadOnlyOps(ops), profile, staging_dir=STAGE, efivars_dir=str(efivars),
        expected_boot_order=tcc.ORDER, out=lines.append,
    )  # fmt: skip
    norm = normaliser(profile, efivars=efivars)
    return PortRun(res.exit_code, exec_lines(ops, norm), lines, extra={"res": res, "ops": ops})


def _pf_over(**over):
    return lambda efivars: over


EFI_BOOTNEXT = "BootNext: 0002\n" + tcc.EFI_OK
EFI_BOOTORDER = tcc.EFI_OK.replace(tcc.ORDER, "0002,0001,0000,0003,0004")
EFI_STALE = tcc.EFI_OK + f"Boot0005* {LABEL}\tHD(11,GPT,1,0x0,0x0)/File(\\EFI\\BOOT\\BOOTAA64.EFI)\n"
PF_FAULTS = {
    "parttable": dict(over=_pf_over(**{f"sfdisk --dump {tcc.DISK}": FOREIGN_DUMP})),
    "sectors": dict(over=_pf_over(**{f"blockdev --getsz {tcc.DISK}": "119537664\n"})),
    "readonly": dict(over=_pf_over(**{f"blockdev --getro {tcc.DISK}": "1\n"})),
    "mounted": dict(over=_pf_over(**{"findmnt -rn -o SOURCE": "/dev/nvme0n1p1\n/dev/mmcblk0p3\n"})),
    "bootnext": dict(over=_pf_over(**{"efibootmgr -v": EFI_BOOTNEXT})),
    "bootorder": dict(over=_pf_over(**{"efibootmgr -v": EFI_BOOTORDER})),
    "stale": dict(over=_pf_over(**{"efibootmgr -v": EFI_STALE})),
    "noC": dict(over=_pf_over(**{"efibootmgr --help": "Usage: efibootmgr [-c]\n  -c | --create\n"})),
    "efivarfsro": dict(
        over=lambda ef: {f"findmnt -no OPTIONS {ef}": "ro,nosuid,nodev,noexec,relatime\n"}
    ),
    "secureboot": dict(secure_boot=1),
    "corrupt": dict(
        over=_pf_over(**{"sha256sum --strict -c MANIFEST.hashes": OpResult(rc=1, stdout=b"img0.bin: FAILED\n")})
    ),
    "space": dict(
        over=_pf_over(**{f"df -Pk {tcc.STAGE}": f"Filesystem 1K-blocks Used Available Use% Mounted on\ntmpfs 900000 300000 600000 34% {tcc.STAGE}\n"})
    ),
}  # fmt: skip


def _pf_fault(kw):
    return lambda tmp: _pf(tmp, **kw)


def s_pf_sb_absent(tmp):
    return _pf(tmp, secure_boot=None)


def s_pf_image_missing(tmp):
    gone = OpFailed(["stat", "-c", "%s", f"{STAGE}/img0.bin"], 1, "No such file or directory")
    return _pf(
        tmp,
        over=_pf_over(**{
            f"stat -c %s {STAGE}/img0.bin": gone,
            "sha256sum --strict -c MANIFEST.hashes": OpResult(rc=1, stdout=b"img0.bin: FAILED open or read\n"),
        }),
    )  # fmt: skip


def s_pf_missing_tool(tmp):
    gone = OpFailed(["efibootmgr"], None, "tool 'efibootmgr' not found")
    return _pf(tmp, over=_pf_over(**{"efibootmgr -v": gone, "efibootmgr --help": gone}))


def s_pf_no_manifest(tmp):
    return _pf(
        tmp,
        over=_pf_over(**{
            f"read_file {STAGE}/MANIFEST.hashes": FileNotFoundError("MANIFEST.hashes"),
            "sha256sum --strict -c MANIFEST.hashes": OpResult(
                rc=1, stderr="sha256sum: MANIFEST.hashes: No such file or directory\n"
            ),
        }),
    )  # fmt: skip


def s_pf_efi_fail(tmp):
    """Every efibootmgr call exits 1, as the kit's stub does when efi.fail exists."""
    return _pf(tmp, over=_pf_over(**{"efibootmgr -v": OpResult(rc=1), "efibootmgr --help": OpResult(rc=1)}))


# ---- window: readback and cleanup

MNT, OUT = "<TMP>/mnt", "<TMP>/out"
RB_DIRS = (pathlib.Path(MNT), pathlib.Path(OUT))
ONESHOT = f"Boot0005* {LABEL}\tHD(11,GPT,1,0x0,0x0)/File(\\EFI\\BOOT\\BOOTAA64.EFI)bootmode=bootimg\n"


def _rb(tmp, *, journal=True, efi=tcrb.EFI, reference=tcrb.ORDER, outfs="tmpfs\n", mount=None):
    ops = RecordingOps(tcrb.script(RB_DIRS, journal=journal, efi=efi, outfs=outfs, mount=mount))
    lines = []
    res = run_readback(
        ops, shipped_profile(), mount_dir=MNT, out_dir=OUT, reference_boot_order=reference,
        copier=lambda s, d: None, list_logs=lambda m: [], makedirs=lambda *a, **k: None,
        # The kit asked about the output directory itself; the port asks about its nearest existing
        # ancestor when the directory is not there yet. The literal "<TMP>" paths never exist, so
        # hand the probe the path as is to keep the pinned call sequence.
        nearest_existing=lambda p: p,
        out=lines.append,
    )  # fmt: skip
    return PortRun(res.exit_code, ops.log, lines, extra={"res": res})


def s_rb_default(tmp):
    return _rb(tmp)


def s_rb_entry(tmp):
    return _rb(tmp, journal=False, efi="BootNext: 0005\n" + tcrb.EFI + ONESHOT)


def s_rb_fallback(tmp):
    return _rb(tmp, journal=False, reference=tcrb.ORDER)


def s_rb_differs(tmp):
    return _rb(tmp, journal=False, efi=tcrb.EFI.replace(tcrb.ORDER, "0005," + tcrb.ORDER))


def s_rb_notmpfs(tmp):
    return _rb(tmp, journal=False, outfs="ext4\n")


def s_rb_mountfail(tmp):
    return _rb(
        tmp, journal=False,
        mount=OpFailed(["mount", "-o", "ro", "-t", "btrfs", tcrb.PART, MNT], 32, "mount: wrong fs type"),
    )  # fmt: skip


def s_rb_missing_tool(tmp):
    ops = RecordingOps(
        {**tcrb.script(RB_DIRS), "lsblk -dn -o NAME": OpFailed(["lsblk"], None, "tool 'lsblk' not found")}
    )
    lines = []
    try:
        res = run_readback(
            ops, shipped_profile(), mount_dir=MNT, out_dir=OUT, reference_boot_order=tcrb.ORDER,
            copier=lambda s, d: None, list_logs=lambda m: [], makedirs=lambda *a, **k: None, out=lines.append,
        )  # fmt: skip
    except Exception as exc:  # noqa: BLE001 - the runner turns this into EXIT_ERROR
        return PortRun(runner.EXIT_ERROR, ops.log, lines, raised=exc)
    return PortRun(res.exit_code, ops.log, lines)


# ---- restore

REF_ORDER = "0001,0002,0003"
TRIM = "Boot0001* UEFI NVMe\nBoot0002* UEFI eMMC\n"


def _efi(order=REF_ORDER, nxt=None, current="0001", extra=()):
    head = (f"BootNext: {nxt}\n" if nxt else "") + f"BootCurrent: {current}\nTimeout: 5 seconds\nBootOrder: {order}\n"
    return head + TRIM + "".join(extra)


def _restore(tmp, *, armed=True, queue=None, phase="armed"):
    staging = tmp / "var" / "lib" / "staging"
    staging.mkdir(parents=True)
    state_dir = tmp / "state"
    state_dir.mkdir()
    profile = NS(arm=NS(strategy="uefi-bootnext", params={"label": LABEL}), staging=NS(dir=str(staging)))
    if armed:
        s = statemod.create_run(
            state_dir, run_id="r1", profile_hash="p", plan_hash="q", board_identity={}, image_roles=[], arm=True
        )
        s = statemod.transition(s, "table-writing")
        s = statemod.transition(s, "table-written")
        s = statemod.transition(s, "verified")
        rec = ArmRecord(
            entry_number="0005", label=LABEL, preexisting_boot_order=REF_ORDER, preexisting_next="", next_armed=True
        )
        s = statemod.transition(s, "armed", armed=rec.to_dict())
        if phase == "complete":
            statemod.transition(s, "complete")
    ops = RecordingOps({"efibootmgr -v": queue or [_efi()] * 3})
    removed, lines = [], []
    res = run_restore(
        ops, profile, state_dir=state_dir, staging_dir=str(staging), remove_tree=removed.append, out=lines.append,
        ack_run_id="r1",  # the port requires the acknowledgement for a non-terminal run (5.15); the kit had none
    )
    return PortRun(res.exit_code, ops.log, lines, extra={"removed": removed, "res": res})


def s_cleanup(tmp):
    return _restore(tmp, queue=[_efi(nxt="0005", extra=[ONESHOT])] * 2 + [_efi()])


def s_cleanup_none(tmp):
    return _restore(tmp, queue=[_efi()] * 3)


def s_cleanup_two(tmp):
    other = ONESHOT.replace("Boot0005", "Boot0006")
    return _restore(tmp, queue=[_efi(extra=[ONESHOT, other])] * 2 + [_efi(extra=[other])])


def s_cleanup_next_only(tmp):
    return _restore(tmp, queue=[_efi(nxt="0002")] * 3)


def s_ok4(tmp):
    return _restore(tmp, phase="complete", queue=[_efi(nxt="0005", extra=[ONESHOT])] * 2 + [_efi()])


def s_rnostate(tmp):
    return _restore(tmp, armed=False)


def s_na(tmp):  # pragma: no cover - NA cases are never run
    raise AssertionError("an NA case was run")


# ------------------------------------------------------------------- CASES

Expectation = namedtuple("Expectation", "kind detail diff reads exit_class")
Expectation.__new__.__defaults__ = (None, None, False)  # diff, reads, exit_class


def exact(detail):
    return Expectation("EXACT", detail)


def outcome(detail, reads=None, exit_class=False):
    return Expectation("OUTCOME", detail, None, reads, exit_class)


def differs(diff, detail):
    return Expectation("DIFFERS", detail, diff)


def na(reason):
    return Expectation("NA", reason)


# Kit-only reads the port does elsewhere or never: `efibootmgr --help` is the
# capability probe of the port's `check`, not of `plan`.
PLAN_REF = dict(drop={"efibootmgr --help"}, unordered=())
PF_REF = dict(drop=(), unordered={"efibootmgr -v"})

OK_MUT = "same mutating sequence as the kit: sfdisk, udevadm settle, 7 dd, efibootmgr -C, efibootmgr -n"

CASES = {
    "install:dry": outcome("plan: exit 0, no mutating call; body compared separately with real-board-dry-run.txt", reads=PLAN_REF),
    "install:dry#2": na("the kit's plain-form 'NVME-HIDE-ARG:' manifest line; the port takes the argument from the profile guard, not the manifest"),
    "install:ok": differs("D5+D6", OK_MUT),
    "install:ok#2": outcome("second plan on the written disk is refused (exit 1, no mutating call)", reads=PLAN_REF),
    "install:ok#3": na("restore --dry-run: the port's restore has no dry-run mode"),
    "install:ok#4": differs("D8", "restore only disarms (efibootmgr -N, -B); it never deletes partitions or wipes the table"),
    "install:ok#5": differs("D5+D6", "re-install on a fresh board: " + OK_MUT),
    "install:rmismatch1": differs("D5+D6", OK_MUT),
    "install:rmismatch1#2": na("the kit's label-id check before deleting partitions; the port's restore never touches the table"),
    "install:rmismatch2": differs("D5+D6", OK_MUT),
    "install:rmismatch2#2": na("the kit's partition-vs-record check before deleting partitions; the port's restore never touches the table"),
    "install:rnostate": differs("D8", "restore with no run state exits 0 and cleans staging; the kit refuses"),
    "install:disk-nvme0n1": differs("D7", "NVMe target refused before any call"),
    "install:disk-nvme0n1p1": differs("D7", "NVMe partition target refused before any call"),
    "install:disk-sda": differs("D7", "non-profile disk refused (identity mismatch) with zero mutating calls"),
    "install:disk-nvme-dry": differs("D7", "NVMe target refused by plan as well"),
    "install:badsum": outcome("flipped manifest checksum: plan refuses, no mutating call", reads=PLAN_REF),
    "install:modified": outcome("image changed after the manifest: plan refuses, no mutating call", reads=PLAN_REF),
    "install:foreign": outcome("foreign partition table: plan refuses, no mutating call", reads=PLAN_REF),
    "install:foreign-lsblk": outcome("lsblk shows a partition: plan refuses, no mutating call", reads=PLAN_REF),
    "install:mounted": outcome("a partition is mounted: plan refuses, no mutating call", reads=PLAN_REF),
    "install:badcmd": outcome("staged boot image without the NVMe-hiding argument: write refused before any mutation, exit 1"),
    "install:unseated": differs("D5+D6", "guard-less profile (the kit's --nvme-unseated): " + OK_MUT),
    "install:readback": outcome("cmdline read back from the partition lacks the argument: sfdisk, settle, 7 dd, nothing armed, exit 1"),
    "install:extracmd": differs("D5+D6", "argument in extra_cmdline (offset 608) accepted: " + OK_MUT),
    "install:nearmiss": outcome("staged near-miss token: write refused before any mutation, exit 1"),
    "install:hdrv3": outcome("staged header version 3: write refused before any mutation, exit 1"),
    "install:noarg": outcome("staged boot image with no source of the NVMe-hiding argument: refused before any mutation, exit 1"),
    "install:bochange": outcome("efibootmgr -C changes BootOrder: sfdisk, settle, 7 dd, -C, never -n; exit 1"),
    "install:noc": outcome("efibootmgr without -C: write refused by the pre-flight check, no mutating call"),
    "install:nocfb": na("the kit's --fallback-bootnext-0002 option; the port has no fallback arming"),
    "install:devimages": outcome("staging directory under /dev: the profile loader refuses, no call at all", exit_class=True),
    "install:nondevimages": differs("D5+D6", "staging directory outside /dev: " + OK_MUT),
    "window:pf-good": outcome("check: exit 0, 14/14, no mutating call", reads=PF_REF),
    **{
        f"window:pf-{k}": differs("D1", f"{k}: FAIL line and exit 1, but checks: 14/14 (examined) instead of 13/14")
        for k in PF_FAULTS
    },
    "window:pf-sb-absent": differs("D2", "missing SecureBoot variable is a FAIL (exit 1); the kit passed with a warning"),
    "window:pf-image-missing": differs("D1", "staged image missing: FAIL and exit 1, checks counted as examined"),
    "window:pf-missing-tool": outcome("efibootmgr missing: nothing failed, checks not examined, exit 2"),
    "window:pf-no-manifest": outcome("MANIFEST.hashes absent: not examined, exit 2"),
    "window:pf-efi-fail": outcome("efibootmgr failing: not examined, exit 2"),
    "window:pf-noroot": na("the kit's own root check; the port's check runs inside the bundle under the host layer's sudo and has no root self-check"),
    "window:rb-default": exact("readback: identical call sequence, exit 0"),
    "window:rb-entry": differs("D4", "readback always runs `ls -laR` on the journal path; the kit used a file test"),
    "window:rb-fallback": differs("D4", "readback always runs `ls -laR` on the journal path; the kit used a file test"),
    "window:rb-differs": differs("D4", "readback always runs `ls -laR` on the journal path; the kit used a file test"),
    "window:rb-notmpfs": exact("readback: out dir not on tmpfs, refuses before mounting"),
    "window:rb-mountfail": exact("readback: failed ro mount is reported, exit 1, no umount"),
    "window:rb-missing-tool": outcome("lsblk missing: no mutating call, exit 2"),
    "window:rb-cleanup": outcome("restore with the recorded entry: efibootmgr -N then -B -b 0005, exit 0"),
    "window:rb-cleanup-two": differs("D8", "restore removes only the recorded entry; the kit refused on two labelled entries"),
    "window:rb-cleanup-none": outcome("restore with nothing left to remove: exit 0, no mutating call"),
    "window:rb-cleanup-next-only": differs("D8", "restore leaves a BootNext it did not set; the kit cleared it"),
}  # fmt: skip

SCENARIOS = {
    "install:dry": s_dry,
    "install:ok": s_install_ok,
    "install:ok#2": s_ok2,
    "install:ok#4": s_ok4,
    "install:ok#5": s_install_ok,
    "install:rmismatch1": s_install_ok,
    "install:rmismatch2": s_install_ok,
    "install:rnostate": s_rnostate,
    "install:disk-nvme0n1": _disk("/dev/nvme0n1"),
    "install:disk-nvme0n1p1": _disk("/dev/nvme0n1p1"),
    "install:disk-sda": _disk("/dev/sda"),
    "install:disk-nvme-dry": _disk("/dev/nvme0n1"),
    "install:badsum": s_badsum,
    "install:modified": s_modified,
    "install:foreign": s_foreign,
    "install:foreign-lsblk": s_foreign_lsblk,
    "install:mounted": s_mounted,
    "install:badcmd": s_badcmd,
    "install:unseated": s_unseated,
    "install:readback": s_readback,
    "install:extracmd": s_extracmd,
    "install:nearmiss": s_nearmiss,
    "install:hdrv3": s_hdrv3,
    "install:noarg": s_noarg,
    "install:bochange": s_bochange,
    "install:noc": s_noc,
    "install:devimages": s_devimages,
    "install:nondevimages": s_install_ok,
    "window:pf-good": lambda tmp: _pf(tmp),
    **{f"window:pf-{k}": _pf_fault(kw) for k, kw in PF_FAULTS.items()},
    "window:pf-sb-absent": s_pf_sb_absent,
    "window:pf-image-missing": s_pf_image_missing,
    "window:pf-missing-tool": s_pf_missing_tool,
    "window:pf-no-manifest": s_pf_no_manifest,
    "window:pf-efi-fail": s_pf_efi_fail,
    "window:rb-default": s_rb_default,
    "window:rb-entry": s_rb_entry,
    "window:rb-fallback": s_rb_fallback,
    "window:rb-differs": s_rb_differs,
    "window:rb-notmpfs": s_rb_notmpfs,
    "window:rb-mountfail": s_rb_mountfail,
    "window:rb-missing-tool": s_rb_missing_tool,
    "window:rb-cleanup": s_cleanup,
    "window:rb-cleanup-two": s_cleanup_two,
    "window:rb-cleanup-none": s_cleanup_none,
    "window:rb-cleanup-next-only": s_cleanup_next_only,
}


@pytest.fixture(scope="module")
def runs(tmp_path_factory):
    """Run every non-NA scenario once; a crash is attributed to its own case."""
    out = {}
    for name, fn in SCENARIOS.items():
        tmp = tmp_path_factory.mktemp(re.sub(r"\W+", "_", name))
        try:
            out[name] = fn(tmp)
        except Exception as exc:  # noqa: BLE001
            out[name] = PortRun(-1, raised=exc)
    return out


def _runs_ok(run):
    if run.exit == -1 and run.raised is not None:
        pytest.fail(f"scenario crashed: {type(run.raised).__name__}: {run.raised}")


# ------------------------------------------------------------- table tests


def test_golden_log_has_every_listed_case(golden):
    assert len(golden) == 87
    assert list(golden) == ALL_NAMES
    for name, g in golden.items():
        assert g.exit >= 0, f"{name} has no exit= line"


def test_cases_cover_exactly_the_63_install_and_window_cases(golden):
    found = [n for n in golden if n.startswith(("install:", "window:"))]
    assert len(found) == 63 == len(CASES)
    assert set(CASES) == set(found)
    assert set(SCENARIOS) | {n for n, e in CASES.items() if e.kind == "NA"} == set(CASES)
    assert not set(SCENARIOS) & {n for n, e in CASES.items() if e.kind == "NA"}


def test_every_case_has_one_closed_verdict():
    kinds = [e.kind for e in CASES.values()]
    assert set(kinds) <= {"EXACT", "OUTCOME", "DIFFERS", "NA"}
    assert sum(kinds.count(k) for k in ("EXACT", "OUTCOME", "DIFFERS", "NA")) == 63
    for name, e in CASES.items():
        assert e.detail, name
        assert (e.diff is not None) == (e.kind == "DIFFERS"), name


# --------------------------------------------------------- comparison logic


def _ordered_subsequence(wanted, have) -> list:
    """Items of ``wanted`` that do not appear, in order, in ``have``."""
    missing, i = [], 0
    for w in wanted:
        try:
            i = have.index(w, i) + 1
        except ValueError:
            missing.append(w)
    return missing


def assert_exit(g: Golden, run: PortRun, exit_class=False):
    if exit_class:
        assert (g.exit == 0) == (run.exit == 0), f"kit exit={g.exit}, port exit={run.exit}"
    else:
        assert run.exit == g.exit, f"kit exit={g.exit}, port exit={run.exit}\n{run.text}"


def assert_reads(g: Golden, run: PortRun, ref: dict):
    wanted = [ln for ln in g.kit_reads if ln not in ref["drop"]]
    present = [ln for ln in wanted if ln in ref["unordered"]]
    ordered = [ln for ln in wanted if ln not in ref["unordered"]]
    assert _ordered_subsequence(ordered, run.lines) == [], f"kit reads missing or reordered in the port:\n{run.lines}"
    for ln in present:
        assert ln in run.lines, f"kit read {ln!r} never issued by the port"


def check_exact(name, g, run):
    assert run.lines == g.lines, f"{name}: call sequence differs\nkit : {g.lines}\nport: {run.lines}"
    assert_exit(g, run)


def check_outcome(name, g, run, e):
    assert_exit(g, run, e.exit_class)
    if g.exit == 0:
        assert run.muts == g.muts, f"{name}: mutating sequence differs\nkit : {g.muts}\nport: {run.muts}"
    elif name == "install:readback" or name == "install:bochange":
        # failure after the write: the kit's own mutating sequence applies
        assert run.muts == g.muts, f"{name}: mutating sequence differs\nkit : {g.muts}\nport: {run.muts}"
    else:
        assert g.muts == [], f"{name}: golden refusal unexpectedly mutated: {g.muts}"
        assert run.muts == [], f"{name}: refusal made mutating calls: {run.muts}"
    if e.reads:
        assert_reads(g, run, e.reads)


# The documented deliberate differences. Each is asserted from both sides.

DIFFERENCES = {
    "D1": "cmd_check counts a FAIL as examined: a single-fault preflight prints `checks: 14/14`, the FAIL line and exits 1; the kit printed `checks: 13/14`.",
    "D2": "a missing SecureBoot variable is a FAIL in the port (Secure Boot state NOT VERIFIED); the kit passed it with a warning.",
    "D3": "device-dependent checks are `not examined` when emmc-exists fails (the kit's pf-* cases force the device to exist).",
    "D4": "cmd_readback always runs `ls -laR` on the journal directory; the kit tested for the directory first.",
    "D5": "cmd_write reads each image back right after writing it (the kit wrote all images, then read all back) and reads the boot header straight from the partition (the kit copied it to a scratch file).",
    "D6": "write requires a plan record and consumes it (a kit install has none): install success cases compare the mutating sequence only.",
    "D7": "the port refuses non-whole-disk and NVMe targets at plan, before any call, with the kit's zero-mutation outcome; the kit takes --disk and refuses in install.sh.",
    "D8": "restore is driven by the recorded arm entry (number AND label), never rolls back the table, and cleans staging when there is no state (spec: 'Restore undoes the arming and removes staging', 'Restore does not claim a data rollback').",
}  # fmt: skip

WRITE_SEQ = (
    ["sfdisk /dev/mmcblk0", "udevadm settle"]
    + [
        f"dd if=<TMP>/images/{k} of=/dev/mmcblk0p{p} bs=1M conv=fsync status=none"
        for k, p in (("boot.img", 3), ("boot.img", 6), ("board.dtb", 4), ("board.dtb", 7),
                     ("esp.img", 11), ("rootfs.erofs-lz4", 1), ("var.btrfs", 16))
    ]
)  # fmt: skip


def d1(name, g, run):
    assert g.exit == 1, "the kit failed this case"
    assert run.exit == 1, run.text
    assert run.muts == [] and g.muts == []
    assert "checks: 14/14" in run.out, run.text
    assert any(ln.startswith("FAIL  ") for ln in run.out)
    assert any(ln.startswith("PREFLIGHT FAIL") for ln in run.out)
    assert_reads(g, run, PF_REF)


def d2(name, g, run):
    assert g.exit == 0, "the kit passed a missing SecureBoot variable"
    assert run.exit == 1
    line = next(ln for ln in run.out if ln.startswith("FAIL  SecureBoot disabled:"))
    assert "NOT VERIFIED" in line
    assert run.muts == []
    assert_reads(g, run, PF_REF)


def d4(name, g, run):
    assert g.exit == run.exit
    extra = f"ls -laR {MNT}/log/journal"
    assert extra in run.lines and extra not in g.lines
    assert [ln for ln in run.lines if ln != extra] == g.lines


def d7(name, g, run):
    assert g.exit == 1 and g.muts == []
    assert run.exit == 1, run.text
    assert run.muts == []
    if "nvme" in name:
        assert run.lines == [], "an NVMe target must be refused before any call"
        assert "NVMe" in run.text
    else:
        assert "identity mismatch" in run.text


def d8(name, g, run):
    if name == "install:ok#4":
        kit_efi = [ln for ln in g.muts if ln.startswith("efibootmgr")]
        assert any(ln.startswith("sfdisk --delete") for ln in g.lines) and any(ln.startswith("wipefs") for ln in g.lines)
        assert run.exit == g.exit == 0
        assert run.muts == kit_efi == ["efibootmgr -N", "efibootmgr -B -b 0005"]
        assert NOTE_LINE in run.out
        assert run.extra["removed"], "staging is removed"
    elif name == "install:rnostate":
        assert g.exit == 1 and g.muts == []
        assert run.exit == 0 and run.lines == [] and run.extra["removed"]
    elif name == "window:rb-cleanup-two":
        assert g.exit == 1 and g.muts == []
        assert run.exit == 0
        assert run.muts == ["efibootmgr -B -b 0005"], "only the recorded entry, never the other labelled one"
    elif name == "window:rb-cleanup-next-only":
        assert g.exit == 0 and g.muts == ["efibootmgr -N"]
        assert run.exit == 0
        assert run.muts == [], "a BootNext this run did not set is left alone"
    else:  # pragma: no cover
        raise AssertionError(name)


def d56(name, g, run):
    """Success: only the MUTATING sequence is comparable (D6), and the port reads each
    image back right after writing it, with no scratch-file header copy (D5)."""
    assert g.exit == run.exit == 0, run.text
    assert run.muts == g.muts, f"{name}: mutating sequence differs\nkit : {g.muts}\nport: {run.muts}"
    assert run.muts == WRITE_SEQ + [
        f"efibootmgr -C -d {DEV} -p 11 -L {LABEL} -l \\EFI\\BOOT\\BOOTAA64.EFI -u bootmode=bootimg",
        "efibootmgr -n 0005",
    ]
    lines = run.lines
    for i, ln in enumerate(lines):
        if is_mut(ln) and ln.startswith("dd "):
            node = next(t[3:] for t in ln.split() if t.startswith("of="))
            assert lines[i + 1].startswith(f"dd if={node} bs=4M iflag=count_bytes count="), lines[i : i + 2]
    assert not any("bhdr" in ln for ln in lines)


DIFF_CHECKS = {"D5+D6": d56, "D1": d1, "D2": d2, "D4": d4, "D7": d7, "D8": d8}


# ---------------------------------------------------------------- per case


@pytest.mark.parametrize("name", [n for n in CASES if CASES[n].kind != "NA"])
def test_case(name, golden, runs):
    e, g, run = CASES[name], golden[name], runs[name]
    _runs_ok(run)
    if e.kind == "EXACT":
        check_exact(name, g, run)
    elif e.kind == "OUTCOME":
        check_outcome(name, g, run, e)
    else:
        DIFF_CHECKS[e.diff](name, g, run)


@pytest.mark.parametrize("name", [n for n in CASES if CASES[n].kind == "NA"])
def test_na_case_is_recorded_with_a_reason(name, golden):
    assert name in golden
    assert len(CASES[name].detail) > 20


# ------------------------------------------------- the nine named differences


def test_every_difference_id_is_documented_and_used():
    used = {e.diff for e in CASES.values() if e.diff}
    ids = {i for d in used for i in d.split("+")}
    assert ids <= set(DIFFERENCES)
    assert set(DIFFERENCES) - ids <= {"D3"}  # D3 has no golden case; asserted by its own test below


def test_d1_single_fault_preflight_counts_failures_as_examined(golden, runs):
    run = runs["window:pf-readonly"]
    assert golden["window:pf-readonly"].exit == 1
    assert run.exit == 1 and "checks: 14/14" in run.out
    assert "FAIL  eMMC not read-only: blockdev --getro: 1 (rc=0)" in run.out
    res = run.extra["res"]
    assert (res.examined, res.total) == (14, 14)


def test_d2_missing_secureboot_is_a_failure(golden, runs):
    d2("window:pf-sb-absent", golden["window:pf-sb-absent"], runs["window:pf-sb-absent"])


def test_d3_device_dependent_checks_are_not_examined_when_emmc_is_absent(tmp_path, golden):
    efivars = _efivars(tmp_path)
    script = tcc.script(efivars, **{f"lsblk -rn -o TYPE {tcc.DISK}": ""})
    ops = RecordingOps(script)
    lines = []
    res = run_check(
        ReadOnlyOps(ops), tcc.shipped(), staging_dir=STAGE, efivars_dir=str(efivars),
        expected_boot_order=tcc.ORDER, out=lines.append,
    )  # fmt: skip
    assert res.exit_code == 1
    for label in ("eMMC not read-only", "eMMC sector count", "eMMC has no partition table", "eMMC not mounted"):
        assert f"FAIL  {label}: not examined: {tcc.DISK} is absent" in lines
    assert (res.examined, res.total) == (10, 14)
    seen = [c.line for c in ops.calls if c.kind == "exec"]
    assert not any(ln.startswith(("blockdev", "sfdisk")) for ln in seen)
    # the kit's pf-good forced the device to exist and ran those reads
    kit = golden["window:pf-good"].lines
    assert f"blockdev --getro {DEV}" in kit and f"sfdisk --dump {DEV}" in kit


def test_d4_readback_always_lists_the_journal_directory(golden, runs):
    for name in ("window:rb-entry", "window:rb-fallback", "window:rb-differs"):
        d4(name, golden[name], runs[name])
    assert "ls -laR" in "\n".join(golden["window:rb-default"].lines)
    assert "ls -laR" not in "\n".join(golden["window:rb-entry"].lines)


def test_d5_each_image_is_read_back_right_after_its_write_and_header_read_is_direct(golden, runs):
    run, g = runs["install:ok"], golden["install:ok"]
    env = run.extra["env"]
    lines = run.lines
    kit = g.lines
    kit_writes = [i for i, ln in enumerate(kit) if ln.startswith("dd ") and " of=/dev/mmcblk0p" in ln]
    kit_reads = [i for i, ln in enumerate(kit) if ln.startswith("dd if=/dev/mmcblk0p") and "iflag=count_bytes" in ln]
    assert max(kit_writes) < min(kit_reads), "the kit writes all images, then reads all back"
    for role, img in env.profile.images.items():
        node = tcw.layout.partition_node(DEV, img.partition)
        w = next(i for i, ln in enumerate(lines) if f" of={node} " in ln)
        assert lines[w + 1].startswith(f"dd if={node} bs=4M iflag=count_bytes count="), lines[w : w + 2]
    assert not any("bhdr" in ln or " of=<" in ln for ln in lines), "the port copies no header to a scratch file"
    assert any("bhdr" in ln for ln in kit)
    assert f"dd if={DEV}p3 bs=2048 count=1 status=none" in lines
    assert any(ln.startswith(f"dd if={DEV}p3 of=") for ln in kit)


def test_d6_write_needs_a_plan_record_and_consumes_it(tmp_path, golden):
    # the kit's install has no plan record; the port refuses without one ...
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    env = tcw.Env(tmp_path / "a")
    res, ops = env.run(plan=None)
    assert res.exit_code == 1 and "no plan record: run plan first" in "\n".join(res.lines)
    assert [ln for ln in ops.log if is_mut(ln)] == []
    # ... and refuses to reuse a plan after a finished run
    env2 = tcw.Env(tmp_path / "b")
    first, _ = env2.run()
    assert first.exit_code == 0
    again, ops2 = env2.run(script=env2.script())
    assert again.exit_code == 1 and "already used by a finished run" in "\n".join(again.lines)
    assert [ln for ln in ops2.log if is_mut(ln)] == []
    # the golden good run carries no plan: only the mutating sequence is comparable
    assert not any("plan" in ln for ln in golden["install:ok"].lines)


def test_d7_disk_refusals(golden, runs):
    for name in ("install:disk-nvme0n1", "install:disk-nvme0n1p1", "install:disk-sda", "install:disk-nvme-dry"):
        d7(name, golden[name], runs[name])


def test_d8_restore_scope(golden, runs):
    for name in ("install:ok#4", "install:rnostate", "window:rb-cleanup-two", "window:rb-cleanup-next-only"):
        d8(name, golden[name], runs[name])


def test_post_write_guard_still_catches_a_bad_written_header(golden, runs):
    """The staged file is fine, the header read back from the partition is not: the
    kit's install:readback. Sequence up to the failure, nothing armed."""
    g, run = golden["install:readback"], runs["install:readback"]
    assert g.exit == run.exit == 1 and run.muts == g.muts == WRITE_SEQ
    assert "guard refused to arm" in run.text and "the board was not armed" in run.text


# --------------------------------------------------------------- plan output


def test_plan_body_equals_real_board_dry_run_byte_for_byte():
    res, _, _ = tcp.plan()
    assert res.exit_code == 0
    marker = res.lines.index("== plan ==")
    body = res.lines[marker + 1 :]
    golden = DRY_RUN.read_text().splitlines()
    assert golden[-1].startswith("DRYRUN-RC=") and golden[-1] == "DRYRUN-RC=0"
    # The one deliberate difference: the bash kit stages a file called MANIFEST,
    # the host stages MANIFEST.hashes, so the port's first body line names that
    # file. Only that exact line shape is normalised back to the kit's wording;
    # the golden is never edited. The assertion below detects a silent golden edit.
    kit_line = f"verifying checksums from {STAGE}/MANIFEST"
    assert golden[0] == kit_line
    assert body[0] == kit_line + ".hashes"
    body = [kit_line] + body[1:]
    assert body == golden[:-1]
    assert "\n".join(body) + "\n" == "\n".join(golden[:-1]) + "\n"


def test_install_dry_read_prefix_is_a_subset_of_the_plan_calls(golden, runs):
    """The kit's dry run reads, in order: blockdev --getsz, findmnt, lsblk,
    sfdisk --dump, efibootmgr -v, efibootmgr --help (plus scratch-file header
    reads of the staged boot image, which the port makes after the write).
    Every one of them appears, in that order, among the port plan's recorded
    calls, except `efibootmgr --help`, which in the port belongs to `check`
    and is asserted against check's recorded calls instead."""
    g, run = golden["install:dry"], runs["install:dry"]
    assert g.exit == 0 and g.muts == [] and run.exit == 0 and run.muts == []
    reads = g.kit_reads
    assert reads == [
        f"blockdev --getsz {DEV}", "findmnt -rn -o SOURCE", f"lsblk -rn -o NAME,TYPE {DEV}",
        f"sfdisk --dump {DEV}", "efibootmgr -v", "efibootmgr --help",
    ]  # fmt: skip
    assert _ordered_subsequence([r for r in reads if r != "efibootmgr --help"], run.lines) == []
    assert "efibootmgr --help" in runs["window:pf-good"].lines


# ------------------------------------------------------ hard rules, all cases

DEV_RE = re.compile(r"^/dev/mmcblk0(p[0-9]+)?$")


def _bad_efi(tok):
    return {"-o", "-O", "-c", "--bootorder", "--create"} & set(tok[1:])


def test_safety_rules_hold_for_every_recorded_port_call(runs):
    seen_mut = 0
    for name, run in runs.items():
        for ln in run.lines:
            tok = ln.split()
            if tok[:1] == ["efibootmgr"]:
                assert not _bad_efi(tok), f"{name}: efibootmgr writes the boot order: {ln}"
            if not is_mut(ln):
                continue
            seen_mut += 1
            for t in tok[1:]:
                t = t.split("=", 1)[1] if t.startswith("of=") else t
                if t.startswith("/dev/"):
                    assert DEV_RE.match(t), f"{name}: mutating call targets {t}: {ln}"
            if tok[0] == "sfdisk" and "--delete" not in tok:
                assert tok[-1] == DEV, f"{name}: {ln}"
        if "write refused:" in run.text or "plan refused:" in run.text:
            assert run.muts == [], f"{name}: a refusal made mutating calls: {run.muts}"
    assert seen_mut > 50


def test_golden_logs_obey_the_same_hard_rules(golden):
    for name, g in golden.items():
        if name.startswith("stage:"):
            continue
        for ln in g.lines:
            tok = ln.split()
            if tok[:1] == ["efibootmgr"]:
                assert not _bad_efi(tok), f"{name}: {ln}"


def test_the_good_run_arms_with_C_and_n_only(runs):
    efi = [ln for ln in runs["install:ok"].lines if ln.startswith("efibootmgr") and ln != "efibootmgr -v"]
    assert efi == [
        "efibootmgr --help",
        f"efibootmgr -C -d {DEV} -p 11 -L {LABEL} -l \\EFI\\BOOT\\BOOTAA64.EFI -u bootmode=bootimg",
        "efibootmgr -n 0005",
    ]


# ------------------------------------------------------------------- stage
# The kit's stage.sh is replaced by host.stage (one tar stream, several short
# ssh commands), so call parity is not a goal. Each kit case maps to the port
# behaviour that corresponds, asserted as an outcome; the rest are NA.

StageMap = namedtuple("StageMap", "port detail")


def _smap(port, detail):
    return StageMap(port, detail)


def _snone(reason):
    return StageMap(None, reason)


def _refused(path_reason):
    return _smap("profile_refuses", path_reason)


STAGE_TABLE = {
    "stage:dry": _smap("dry_run", "host.stage(dry_run=True): no transport call, says no connection is made"),
    "stage:defsrc": _snone("n/a: the kit's default source directory (images-bringup beside the script); the port takes --images explicitly"),
    "stage:oldsrc": _snone("n/a: the kit's default source directory fallback to the older images/ set; the port has no default source"),
    "stage:dev-_dev_shm_x": _refused("/dev/shm/x"),
    "stage:dev-_dev_shm": _refused("/dev/shm"),
    "stage:dev-_dev": _refused("/dev"),
    "stage:dev-_dev_mmcblk0p1": _refused("/dev/mmcblk0p1"),
    "stage:dev-_dev_.._run_x": _refused("/dev/../run/x"),
    "stage:devmsg": _smap("profile_refuses_names_dev", "the refusal message names /dev"),
    "stage:out-_tmp_x": _snone("n/a: the kit only allows /run and /var/tmp; the port's staging.dir is a profile field checked only against /dev, /sys, /proc and '..', so /tmp/x is accepted (pinned by test_stage_allow_list_is_not_ported)"),
    "stage:out-_home_user_x": _snone("n/a: no /run|/var/tmp allow-list in the port (profile field); /home/user/x is accepted"),
    "stage:out-_etc": _snone("n/a: no /run|/var/tmp allow-list in the port (profile field); /etc is accepted by the loader"),
    "stage:out-_runx_y": _snone("n/a: no /run|/var/tmp allow-list in the port (profile field); /runx/y is accepted"),
    "stage:out-_run": _snone("n/a: no /run|/var/tmp allow-list in the port (profile field); /run is accepted by the loader"),
    "stage:out-_var_tmp": _snone("n/a: no /run|/var/tmp allow-list in the port (profile field); /var/tmp is accepted by the loader"),
    "stage:out-_run_.._etc_x": _refused("/run/../etc/x"),
    "stage:ok": _smap("ok", "host.stage: one tar of the manifest images + MANIFEST.hashes + profile.json + bundle, modes 644/755, everything verified"),
    "stage:custom": _smap("custom", "a profile staging.dir other than the default: files land there, remote paths stay inside it"),
    "stage:corrupt": _smap("corrupt_images", "remote sha256sum of the images fails: HostError, nothing reported staged"),
    "stage:corrupt-install.sh": _smap("corrupt_bundle", "the kit's scripts are the port's bundle: remote bundle checksum fails: HostError"),
    "stage:corrupt-preflight.sh": _smap("corrupt_bundle", "the kit's scripts are the port's bundle: remote bundle checksum fails: HostError"),
    "stage:corrupt-readback.sh": _smap("corrupt_bundle", "the kit's scripts are the port's bundle: remote bundle checksum fails: HostError"),
    "stage:sshfail": _smap("ssh_fail", "every ssh command fails: HostError before anything is copied"),
    "stage:badsrc": _smap("missing_source", "image directory absent: HostError, zero transport calls"),
}  # fmt: skip

STAGE_DIRS = {
    "stage:dev-_dev_shm_x": "/dev/shm/x",
    "stage:dev-_dev_shm": "/dev/shm",
    "stage:dev-_dev": "/dev",
    "stage:dev-_dev_mmcblk0p1": "/dev/mmcblk0p1",
    "stage:dev-_dev_.._run_x": "/dev/../run/x",
    "stage:devmsg": "/dev/shm/x",
    "stage:out-_run_.._etc_x": "/run/../etc/x",
}


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


class FakeResolved:
    def __init__(self, data: bytes):
        self.data = data
        self.sha256 = _sha(data)
        self.profile = load_profile_bytes(data)
        self.rechecked = 0

    def recheck(self):
        self.rechecked += 1


def _stage_kit(tmp, staging_dir=None):
    doc = json.loads(FIXTURE_NONE.read_text())
    if staging_dir is not None:
        doc["staging"]["dir"] = staging_dir
    resolved = FakeResolved(json.dumps(doc).encode())
    images = tmp / "images"
    images.mkdir()
    files = {"boot.img": b"B" * 3000, "rootfs.img": b"R" * 5000}
    for n, d in files.items():
        (images / n).write_bytes(d)
    (images / "MANIFEST.hashes").write_text("".join(f"{_sha(d)}  {n}\n" for n, d in files.items()))
    (images / "NOTES.md").write_text("never staged")
    info = bundle.build_bundle(resolved.data, tmp / "b.pyz", "parity-1")
    return resolved, images, info.path


def _stage_handler(fail_on=None, fail_all=False):
    def h(argv, stdin, sudo):
        joined = " ".join(argv)
        if fail_all:
            return RunResult(255, b"", b"ssh: connect failed")
        if fail_on and fail_on(joined, stdin):
            return RunResult(1, b"x: FAILED", b"")
        if "df -Pk" in joined or "df" in argv:
            return _df_ok()
        if argv[:2] == ["id", "-un"]:
            return RunResult(0, b"operator\n", b"")
        return RunResult(0, b"", b"")

    return h


def _df_ok():
    out = "Filesystem 1024-blocks Used Available Capacity Mounted on\ntmpfs 999999 1 10000000 1% /run\n"
    return RunResult(0, out.encode(), b"")


def run_stage_case(tmp, port):
    out = []
    transport = None
    try:
        if port in ("profile_refuses", "profile_refuses_names_dev"):
            raise AssertionError("handled by the caller")
        if port == "dry_run":
            resolved, images, bpath = _stage_kit(tmp)
            host.stage(None, resolved.profile, resolved, images, bpath, dry_run=True, out=out.append)
            return NS(ok=True, calls=[], out=out, resolved=resolved, error=None)
        if port == "missing_source":
            resolved, images, bpath = _stage_kit(tmp)
            transport = StubTransport(_stage_handler())
            host.stage(transport, resolved.profile, resolved, tmp / "nonexistent", bpath, out=out.append)
            return NS(ok=True, calls=transport.calls, out=out, resolved=resolved, error=None)
        staging = "/var/tmp/alt-stage" if port == "custom" else None
        resolved, images, bpath = _stage_kit(tmp, staging)
        if port == "corrupt_images":
            fail = lambda j, s: "MANIFEST.hashes" in j and "--strict -c" in j  # noqa: E731
            transport = StubTransport(_stage_handler(fail_on=fail))
        elif port == "corrupt_bundle":
            fail = lambda j, s: s is not None and b"profile.json" in s  # noqa: E731
            transport = StubTransport(_stage_handler(fail_on=fail))
        elif port == "ssh_fail":
            transport = StubTransport(_stage_handler(fail_all=True))
        else:
            transport = StubTransport(_stage_handler())
        host.stage(transport, resolved.profile, resolved, images, bpath, out=out.append)
        return NS(ok=True, calls=transport.calls, out=out, resolved=resolved, error=None, bundle=bpath)
    except (HostError, ProfileError) as exc:
        return NS(ok=False, calls=transport.calls if transport else [], out=out, resolved=None, error=exc)


def _kit_stage(golden, name):
    g = golden[name]
    return g.exit, sum(1 for ln in g.lines if ln.startswith("CALL "))


def test_stage_table_covers_exactly_the_24_stage_cases(golden):
    found = [n for n in golden if n.startswith("stage:")]
    assert len(found) == 24
    assert set(STAGE_TABLE) == set(found) == set(STAGE_NAMES)


@pytest.mark.parametrize("name", STAGE_NAMES)
def test_stage_case(name, tmp_path, golden):
    m = STAGE_TABLE[name]
    kit_exit, kit_calls = _kit_stage(golden, name)
    if m.port is None:
        assert m.detail.startswith("n/a: "), name
        return
    if m.port.startswith("profile_refuses"):
        # the kit refuses before any ssh call; the port's profile loader rejects the
        # staging directory before a transport exists
        assert kit_exit != 0 and kit_calls == 0
        doc = json.loads(FIXTURE_NONE.read_text())
        doc["staging"]["dir"] = STAGE_DIRS[name]
        with pytest.raises(ProfileError) as ei:
            load_profile_bytes(json.dumps(doc).encode())
        if m.port == "profile_refuses_names_dev":
            assert "/dev" in str(ei.value)
        return
    r = run_stage_case(tmp_path, m.port)
    if m.port == "dry_run":
        assert kit_exit == 0 and kit_calls == 0
        assert r.ok and r.calls == [] and "stage dry run: no connection is made" in r.out
    elif m.port == "missing_source":
        assert kit_exit != 0 and kit_calls == 0
        assert not r.ok and isinstance(r.error, HostError) and r.calls == []
    elif m.port in ("ok", "custom"):
        assert kit_exit == 0 and kit_calls == 1
        assert r.ok, r.error
        tars = [c for c in r.calls if c.kind == "put_tar"]
        assert len(tars) == 1
        staging = r.resolved.profile.staging.dir
        if m.port == "custom":
            assert staging == "/var/tmp/alt-stage"
        t = tars[0]
        assert t.dest_dir == staging
        assert set(t.files) == {"boot.img", "rootfs.img", "MANIFEST.hashes", "profile.json", r.bundle.name}
        assert t.modes[r.bundle.name] == 0o755 and all(m_ == 0o644 for n, m_ in t.modes.items() if n != r.bundle.name)
        assert "NOTES.md" not in t.files
        for c in r.calls:
            for a in c.argv:
                if a.startswith("/"):
                    assert a == staging or a.startswith(staging + "/") or a in ("/dev/null",), (c.argv, staging)
            assert not any(".." in a for a in c.argv)
        verifies = [c for c in r.calls if "--strict" in " ".join(c.argv)]
        assert len(verifies) == 2
    elif m.port in ("corrupt_images", "corrupt_bundle"):
        assert kit_exit != 0
        assert not r.ok and isinstance(r.error, HostError) and "verification" in str(r.error)
        assert sum(1 for c in r.calls if c.kind == "put_tar") == 1  # copied, then the check failed
        assert not any("staged" in ln for ln in r.out)
    elif m.port == "ssh_fail":
        assert kit_exit != 0
        assert not r.ok and isinstance(r.error, HostError)
        assert not any(c.kind == "put_tar" for c in r.calls)
        assert not any("staged" in ln for ln in r.out)
    else:  # pragma: no cover
        raise AssertionError(m.port)


def test_stage_allow_list_is_not_ported():
    """Pins what the n/a stage:out-* rows rely on: the loader accepts these."""
    for d in ("/tmp/x", "/home/user/x", "/etc", "/runx/y", "/run", "/var/tmp"):
        doc = json.loads(FIXTURE_NONE.read_text())
        doc["staging"]["dir"] = d
        assert load_profile_bytes(json.dumps(doc).encode()).staging.dir == d


def test_stage_kit_refusals_made_no_ssh_call(golden):
    for name in STAGE_NAMES:
        if name.startswith(("stage:dev-", "stage:out-", "stage:devmsg")):
            kit_exit, kit_calls = _kit_stage(golden, name)
            assert kit_exit != 0 and kit_calls == 0, name
