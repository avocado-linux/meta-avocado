"""Tests for the read-only ``check`` subcommand (pre-flight)."""

import inspect
import json
import pathlib

import pytest

from avocado_flash_remote import cmd_check
from avocado_flash_remote.cmd_check import CheckResult, run_check
from avocado_flash_remote.ops import (
    MutationRefused,
    OpFailed,
    OpResult,
    ReadOnlyOps,
    RecordingOps,
    vector_mutates,
)
from avocado_flash_remote.profile import load_profile_bytes

PROFILES = pathlib.Path(__file__).resolve().parents[2] / "avocado_flash_remote" / "profiles"
SHIPPED = PROFILES / "jetson-agx-orin-j5012.json"
DISK = "/dev/mmcblk0"
STAGE = "/run/emmc-test-images"
ORDER = "0001,0002,0000,0003,0004"
LABEL = "UEFI eMMC Device"
ENTRY_LINE = f"Boot0002* {LABEL}\tVenHw(1e5a432c-0000-0000-0000-000000000000)/SD(0)\n"
EFI_OK = (
    "BootCurrent: 0001\n"
    "Timeout: 5 seconds\n"
    f"BootOrder: {ORDER}\n"
    "Boot0000* UEFI Shell\n"
    "Boot0001* UEFI NVMe\n"
    + ENTRY_LINE
)
MANIFEST = "".join(f"{'a' * 64}  img{i}.bin\n" for i in range(5))
MIN_KIB = 716800
GNU_TOOLS = {
    "install --version": "install (GNU coreutils) 9.4\n",
    "sha256sum --version": "sha256sum (GNU coreutils) 9.4\n",
    "dd --version": "dd (GNU coreutils) 9.4\n",
}
BUSYBOX_REFUSAL = OpResult(rc=1, stderr="unrecognized option: version\nBusyBox v1.36.1 multi-call binary.\n")


def shipped():
    return load_profile_bytes(SHIPPED.read_bytes())


def profile_with(checks, identity=None):
    doc = json.loads(SHIPPED.read_text())
    doc["checks"] = list(checks)
    if identity is not None:
        doc["target"]["identity"] = identity
    return load_profile_bytes(json.dumps(doc).encode())


@pytest.fixture
def efivars(tmp_path):
    d = tmp_path / "efivars"
    d.mkdir()
    (d / "SecureBoot-8be4df61-93ca-11d2-aa0d-00e098032b8c").write_bytes(bytes([7, 0, 0, 0, 0]))
    return d


def script(efivars, **over):
    s = {
        f"lsblk -rn -o TYPE {DISK}": "disk\n",
        f"blockdev --getro {DISK}": "0\n",
        f"blockdev --getsz {DISK}": "122314752\n",
        f"sfdisk --dump {DISK}": OpResult(rc=1, stderr=f"sfdisk: {DISK}: does not contain a recognized partition table\n"),
        "findmnt -rn -o SOURCE": "/dev/nvme0n1p1\n/dev/nvme0n1p2\n",
        "efibootmgr --help": "Usage: efibootmgr [-n|-N]\n  -n | --bootnext XXXX\n  -N | --delete-bootnext\n",
        "efibootmgr -v": EFI_OK,
        f"findmnt -no OPTIONS {efivars}": "rw,nosuid,nodev,noexec,relatime\n",
        f"read_file {STAGE}/MANIFEST.hashes": MANIFEST,
        "sha256sum --strict -c MANIFEST.hashes": "".join(f"img{i}.bin: OK\n" for i in range(5)),
        f"df -Pk {STAGE}": f"Filesystem 1K-blocks Used Available Use% Mounted on\ntmpfs 100 1 12156576 1% {STAGE}\n",
        f"findmnt -no FSTYPE -T {STAGE}": "tmpfs\n",
        "uname -r": "5.15.148-tegra\n",
        "docker ps -q": "a\nb\nc\n",
        **GNU_TOOLS,
        "read_file /sys/block/mmcblk0/device/life_time": "0x01 0x01\n",
        "read_file /sys/block/mmcblk0/device/pre_eol_info": "0x01\n",
    }
    for i in range(5):
        s[f"stat -c %s {STAGE}/img{i}.bin"] = "10\n"
    s.update(over)
    return s


def run(efivars, ops=None, profile=None, readonly=True, **over):
    rec = ops or RecordingOps(script(efivars, **over))
    wrapped = ReadOnlyOps(rec) if readonly else rec
    lines = []
    res = run_check(
        wrapped,
        profile or shipped(),
        staging_dir=STAGE,
        efivars_dir=str(efivars),
        expected_boot_order=ORDER,
        out=lines.append,
    )
    assert lines == res.lines
    return res, rec


def verdict(res, label):
    for ln in res.lines:
        if ln[6:].startswith(label + ":"):
            return ln[:4]
    raise AssertionError(f"no line for {label!r} in {res.lines}")


GOLDEN = [
    "== read-only pre-flight; informational lines are marked INFO and are not counted ==",
    "PASS  eMMC device exists: /dev/mmcblk0",
    "PASS  eMMC not read-only: blockdev --getro: 0 (rc=0)",
    "PASS  eMMC sector count: 122314752 (expected 122314752)",
    "PASS  eMMC has no partition table: sfdisk --dump reports no partition table",
    "PASS  eMMC not mounted: no mmcblk0 source in findmnt",
    "PASS  efibootmgr supports -n and -N: -n and -N listed in --help",
    "PASS  BootOrder unchanged: actual '0001,0002,0000,0003,0004' (expected 0001,0002,0000,0003,0004)",
    "PASS  BootNext unset: unset",
    "PASS  exactly one UEFI eMMC Device entry: Boot0002",
    "PASS  UEFI eMMC Device entry does not precede BootCurrent: 'UEFI eMMC Device' entry does not precede BootCurrent 0001 in BootOrder",
    "PASS  efivarfs mounted read-write: efivarfs options: rw,nosuid,nodev,noexec,relatime",
    "PASS  SecureBoot disabled: SecureBoot final byte = 0",
    "PASS  staged images present: 5 image(s) listed in MANIFEST.hashes are present in /run/emmc-test-images",
    "PASS  staged image checksums: sha256sum --strict -c MANIFEST.hashes: 5 OK",
    "PASS  staging space free: 12156576 KiB free in /run/emmc-test-images, need >= 716800 KiB (700 MiB) beyond the images",
]


def test_all_pass_matches_golden(efivars):
    res, rec = run(efivars)
    assert isinstance(res, CheckResult)
    assert res.lines[: len(GOLDEN)] == GOLDEN
    infos = [ln for ln in res.lines if ln.startswith("INFO")]
    assert "INFO  BootCurrent: 0001" in infos
    assert "INFO  staging filesystem: tmpfs (tmpfs expected; /run/emmc-test-images)" in infos
    assert "INFO  running containers: 3 (they stop at reboot)" in infos
    assert "INFO  kernel: 5.15.148-tegra" in infos
    assert "INFO  eMMC life time: 0x01 0x01 (pre_eol_info 0x01)" in infos
    assert res.lines[-2:] == ["checks: 16/16", "PREFLIGHT PASS"]
    assert (res.exit_code, res.examined, res.total) == (0, 16, 16)
    assert not any(vector_mutates(c.vector) for c in rec.calls if c.kind == "exec")


def test_info_lines_not_counted(efivars):
    res, _ = run(efivars)
    assert res.total == 16
    assert sum(ln.startswith(("PASS", "FAIL")) for ln in res.lines) == 16


FAULTS = [
    ("eMMC device exists", {f"lsblk -rn -o TYPE {DISK}": OpResult(rc=32, stderr="not a block device")}),
    ("eMMC not read-only", {f"blockdev --getro {DISK}": "1\n"}),
    ("eMMC sector count", {f"blockdev --getsz {DISK}": "122314751\n"}),
    ("eMMC has no partition table", {f"sfdisk --dump {DISK}": "label: gpt\n"}),
    ("eMMC not mounted", {"findmnt -rn -o SOURCE": "/dev/mmcblk0p1\n"}),
    ("efibootmgr supports -n and -N", {"efibootmgr --help": "Usage: efibootmgr [-c]\n"}),
    ("BootOrder unchanged", {"efibootmgr -v": EFI_OK.replace(ORDER, "0001,0000")}),
    ("BootNext unset", {"efibootmgr -v": "BootNext: 0005\n" + EFI_OK}),
    ("exactly one UEFI eMMC Device entry", {"efibootmgr -v": EFI_OK + f"Boot0005* {LABEL}\tHD(1)\n"}),
    ("exactly one UEFI eMMC Device entry", {"efibootmgr -v": EFI_OK.replace(ENTRY_LINE, "")}),
    ("efivarfs mounted read-write", {"__efivars_opts__": "ro,nosuid\n"}),
    ("staged images present", {f"stat -c %s {STAGE}/img3.bin": OpFailed(["stat"], 1, "no such file")}),
    ("staged image checksums", {"sha256sum --strict -c MANIFEST.hashes": OpResult(rc=1, stdout=b"img0.bin: FAILED\n")}),
    ("staging space free", {f"df -Pk {STAGE}": "h\ntmpfs 1 1 1024 1% /x\n"}),
]


@pytest.mark.parametrize("label,over", FAULTS, ids=[f[0] for f in FAULTS])
def test_single_fault_fails_but_still_counts_as_examined(efivars, label, over):
    over = dict(over)
    if "__efivars_opts__" in over:
        over[f"findmnt -no OPTIONS {efivars}"] = over.pop("__efivars_opts__")
    res, _ = run(efivars, **over)
    assert verdict(res, label) == "FAIL"
    assert sum(ln.startswith("FAIL") for ln in res.lines) >= 1
    assert res.lines[-2].startswith("checks: ")
    assert res.exit_code == 1
    assert res.lines[-1].startswith("PREFLIGHT FAIL:")
    assert f"[{label}]" in res.lines[-1]
    if label != "eMMC device exists":  # an absent device leaves its dependents unexamined
        assert res.examined == 16 and res.total == 16


def test_secure_boot_enabled_fails(efivars):
    (efivars / "SecureBoot-8be4df61-93ca-11d2-aa0d-00e098032b8c").write_bytes(bytes([7, 0, 0, 0, 1]))
    res, _ = run(efivars)
    assert verdict(res, "SecureBoot disabled") == "FAIL"
    assert res.exit_code == 1


def test_secure_boot_unreadable_fails(efivars):
    (efivars / "SecureBoot-8be4df61-93ca-11d2-aa0d-00e098032b8c").write_bytes(bytes([7, 0, 0, 0]))
    res, _ = run(efivars)
    assert verdict(res, "SecureBoot disabled") == "FAIL"
    assert res.exit_code == 1


def test_secure_boot_variable_absent_fails(efivars):
    for p in efivars.iterdir():
        p.unlink()
    res, _ = run(efivars)
    assert verdict(res, "SecureBoot disabled") == "FAIL"
    assert res.exit_code == 1


def test_unrunnable_check_is_not_examined_exit_2(efivars):
    rec = RecordingOps(script(efivars))
    del rec.script["efibootmgr --help"]
    res, _ = run(efivars, ops=rec)
    assert verdict(res, "efibootmgr supports -n and -N") == "FAIL"
    line = [ln for ln in res.lines if "efibootmgr supports -n and -N" in ln][0]
    assert "not examined" in line
    assert res.lines[-2:][0] == "checks: 15/16"
    assert res.exit_code == 2
    assert res.examined == 15 and res.total == 16
    assert res.lines[-1].startswith("PREFLIGHT FAIL:")


def test_fail_beats_not_examined_for_exit_code(efivars):
    rec = RecordingOps(script(efivars, **{f"blockdev --getro {DISK}": "1\n"}))
    del rec.script["efibootmgr --help"]
    res, _ = run(efivars, ops=rec)
    assert res.exit_code == 1
    assert res.lines[-2] == "checks: 15/16"


def test_efibootmgr_list_failure_not_examines_dependents(efivars):
    res, _ = run(efivars, **{"efibootmgr -v": OpFailed(["efibootmgr", "-v"], 1, "no efi")})
    assert res.exit_code == 2
    assert res.examined == 12
    assert res.lines[-2] == "checks: 12/16"


def test_missing_manifest_not_examined(efivars):
    rec = RecordingOps(script(efivars))
    del rec.script[f"read_file {STAGE}/MANIFEST.hashes"]
    res, _ = run(efivars, ops=rec)
    assert res.exit_code == 2
    assert res.examined == 15  # checksums run sha256sum, which reads the manifest itself


def test_device_absent_makes_dependents_not_examined(efivars):
    res, _ = run(efivars, **{f"lsblk -rn -o TYPE {DISK}": OpResult(rc=32)})
    assert res.exit_code == 1
    assert verdict(res, "eMMC device exists") == "FAIL"
    assert res.examined == 12 and res.total == 16


def test_expected_boot_order_missing_is_not_examined(efivars):
    lines = []
    res = run_check(
        ReadOnlyOps(RecordingOps(script(efivars))),
        shipped(),
        staging_dir=STAGE,
        efivars_dir=str(efivars),
        out=lines.append,
    )
    assert res.exit_code == 2
    assert res.examined == 15


def test_unknown_check_name_is_not_examined(efivars):
    prof = profile_with(["emmc-exists", "no-such-check"])
    res, _ = run(efivars, profile=prof)
    assert res.total == 2 and res.examined == 1
    assert res.exit_code == 2
    assert any(ln.startswith("FAIL  ") and "not examined: no implementation" in ln for ln in res.lines)
    assert res.lines[-2] == "checks: 1/2"


def test_empty_check_list_is_not_a_pass(efivars):
    prof = profile_with([])
    res, _ = run(efivars, profile=prof)
    assert res.total == 0
    assert res.exit_code == 2
    assert res.lines[-1].startswith("PREFLIGHT FAIL")


def test_only_listed_checks_run(efivars):
    prof = profile_with(["emmc-exists"])
    res, rec = run(efivars, profile=prof)
    assert res.exit_code == 0 and (res.examined, res.total) == (1, 1)
    assert res.lines[-2:] == ["checks: 1/1", "PREFLIGHT PASS"]
    assert not any(c.line.startswith("blockdev") for c in rec.calls)


def test_target_identity_sysfs_name(efivars):
    prof = profile_with(["target-identity"])
    res, _ = run(efivars, profile=prof)
    assert res.exit_code == 0
    assert "PASS  target hardware identity: sysfs name mmcblk0" in res.lines


def test_target_identity_sysfs_name_mismatch(efivars):
    prof = profile_with(["target-identity"], {"kind": "sysfs-name", "value": "mmcblk1"})
    res, _ = run(efivars, profile=prof)
    assert res.exit_code == 1
    assert verdict(res, "target hardware identity") == "FAIL"


def test_target_identity_serial(efivars):
    ident = {"kind": "serial", "value": "0xABCD", "sysfs_attr": "serial"}
    prof = profile_with(["target-identity"], ident)
    res, _ = run(efivars, profile=prof, **{"read_file /sys/block/mmcblk0/device/serial": "0xABCD\n"})
    assert res.exit_code == 0
    res, _ = run(efivars, profile=prof, **{"read_file /sys/block/mmcblk0/device/serial": "0x9999\n"})
    assert res.exit_code == 1


def test_target_identity_serial_unreadable_not_examined(efivars):
    ident = {"kind": "serial", "value": "0xABCD", "sysfs_attr": "serial"}
    prof = profile_with(["target-identity"], ident)
    res, _ = run(efivars, profile=prof)
    assert res.exit_code == 2 and res.examined == 0


def test_target_identity_by_path(efivars):
    ident = {"kind": "by-path", "value": "platform-3400000.mmc"}
    prof = profile_with(["target-identity"], ident)
    ls = "ls -l /dev/disk/by-path/platform-3400000.mmc"
    res, _ = run(efivars, profile=prof, **{ls: "lrwxrwxrwx 1 root root 13 Jan 1 00:00 x -> ../../mmcblk0\n"})
    assert res.exit_code == 0
    res, _ = run(efivars, profile=prof, **{ls: "lrwxrwxrwx 1 root root 13 Jan 1 00:00 x -> ../../sda\n"})
    assert res.exit_code == 1


def test_life_time_unavailable_is_info_only(efivars):
    rec = RecordingOps(script(efivars))
    del rec.script["read_file /sys/block/mmcblk0/device/life_time"]
    res, _ = run(efivars, ops=rec)
    assert "INFO  eMMC life time: unavailable" in res.lines
    assert res.exit_code == 0 and res.total == 16


def test_info_failures_never_change_verdict(efivars):
    rec = RecordingOps(script(efivars))
    for k in ("uname -r", "docker ps -q", f"findmnt -no FSTYPE -T {STAGE}"):
        del rec.script[k]
    res, _ = run(efivars, ops=rec)
    assert res.exit_code == 0
    assert any(ln.startswith("INFO  running containers: unknown") for ln in res.lines)


def test_read_only_ops_never_refuse_and_nothing_mutates(efivars):
    res, rec = run(efivars, readonly=True)
    assert res.exit_code == 0
    for c in rec.calls:
        if c.kind == "exec":
            assert not vector_mutates(c.vector), c.line
        else:
            assert c.vector[0] == "read_file"


def test_mutation_refused_surfaces_as_not_examined_not_crash(efivars):
    # A broken check that tried to mutate would be reported, never executed.
    assert not hasattr(cmd_check, "subprocess")


def test_pass_verdict_only_on_exit_zero(efivars):
    res, _ = run(efivars)
    assert ("PREFLIGHT PASS" in res.lines) == (res.exit_code == 0)
    res, _ = run(efivars, **{f"blockdev --getro {DISK}": "1\n"})
    assert "PREFLIGHT PASS" not in res.lines


# ------------------------------------------------- a failing tool is not a verdict


def _assert_not_examined(res, rec, label, needle):
    assert res.exit_code == 2
    assert any(ln.startswith(f"FAIL  {label}: not examined: ") and needle in ln for ln in res.lines), res.lines
    assert "PREFLIGHT FAIL" in res.lines[-1]
    assert not any(vector_mutates(c.vector) for c in rec.calls if c.kind == "exec")


def test_missing_manifest_is_not_examined(efivars):
    over = {
        f"read_file {STAGE}/MANIFEST.hashes": FileNotFoundError("MANIFEST.hashes"),
        "sha256sum --strict -c MANIFEST.hashes": OpResult(
            rc=1, stderr="sha256sum: MANIFEST.hashes: No such file or directory\n"
        ),
    }
    prof = profile_with(["staged-image-checksums"])
    res, rec = run(efivars, profile=prof, **over)
    _assert_not_examined(res, rec, "staged image checksums", "MANIFEST.hashes")
    assert res.examined == 0


def test_failing_checksum_of_listed_image_is_still_a_verdict(efivars):
    over = {
        "sha256sum --strict -c MANIFEST.hashes": OpResult(rc=1, stdout=b"img0.bin: FAILED\n"),
    }
    res, _ = run(efivars, profile=profile_with(["staged-image-checksums"]), **over)
    assert res.exit_code == 1
    assert verdict(res, "staged image checksums") == "FAIL"
    assert not any("not examined" in ln for ln in res.lines)


def test_efibootmgr_help_failing_is_not_examined(efivars):
    over = {"efibootmgr --help": OpResult(rc=1)}
    res, rec = run(efivars, profile=profile_with(["efibootmgr-supports-bootnext"]), **over)
    _assert_not_examined(res, rec, "efibootmgr supports -n and -N", "efibootmgr --help")


def test_efibootmgr_help_without_dash_c_is_still_a_verdict(efivars):
    over = {"efibootmgr --help": "Usage: efibootmgr [-c]\n"}
    res, _ = run(efivars, profile=profile_with(["efibootmgr-supports-bootnext"]), **over)
    assert res.exit_code == 1
    assert verdict(res, "efibootmgr supports -n and -N") == "FAIL"
    assert not any("not examined" in ln for ln in res.lines)


# ---- 5.17: a board-support extension pins the eMMC serial ------------------------

PINNED = "0x0badc0de"
SERIAL_IDENTITY = {"kind": "serial", "value": PINNED, "sysfs_attr": "serial"}
SERIAL_PATH = "read_file /sys/block/mmcblk0/device/serial"


def serial_profile():
    return profile_with(["emmc-exists", "target-identity"], identity=SERIAL_IDENTITY)


def test_shipped_identity_is_the_device_name_compared_with_itself():
    # Why a BSP extension must pin a serial: this identity can never differ.
    assert shipped().target.identity.kind == "sysfs-name"
    assert shipped().target.identity.value == "mmcblk0" == shipped().target.device.rsplit("/", 1)[-1]


def test_matching_serial_passes_the_identity_check(efivars):
    res, _ = run(efivars, profile=serial_profile(), **{SERIAL_PATH: PINNED + "\n"})
    assert res.exit_code == 0
    assert verdict(res, "target hardware identity") == "PASS"


def test_different_serial_fails_the_identity_check(efivars):
    res, _ = run(efivars, profile=serial_profile(), **{SERIAL_PATH: "0x00000001\n"})
    assert res.exit_code == 1
    assert verdict(res, "target hardware identity") == "FAIL"
    assert "not examined" not in "\n".join(res.lines)


def test_missing_serial_attribute_is_not_examined_and_does_not_pass(efivars):
    res, _ = run(efivars, profile=serial_profile(), **{SERIAL_PATH: OpFailed(["cat"], 1, "No such file")})
    assert res.exit_code == 2
    assert verdict(res, "target hardware identity") == "FAIL"
    assert any("target hardware identity" in ln and "not examined" in ln for ln in res.lines)



@pytest.mark.parametrize("tail", [f"{LABEL} old\tHD(1)\n", f"{LABEL}x\tHD(1)\n", f"{LABEL} old\n"])
def test_a_longer_labelled_entry_does_not_count_as_a_second_entry(efivars, tail):
    res, _ = run(efivars, **{"efibootmgr -v": EFI_OK + f"Boot0007* {tail}"})
    assert verdict(res, "exactly one UEFI eMMC Device entry") == "PASS"


@pytest.mark.parametrize("tail", [f"{LABEL}\n", f"{LABEL}  \n", f"{LABEL}\tHD(1)\n"])
def test_a_second_exact_label_fails_and_names_the_count(efivars, tail):
    res, _ = run(efivars, **{"efibootmgr -v": EFI_OK + f"Boot0005* {tail}"})
    assert verdict(res, "exactly one UEFI eMMC Device entry") == "FAIL"
    assert any("2 boot entries labelled" in ln and "Boot0002" in ln and "Boot0005" in ln for ln in res.lines)


def test_zero_entries_fail_and_name_the_count_and_label(efivars):
    res, _ = run(efivars, **{"efibootmgr -v": EFI_OK.replace(ENTRY_LINE, "")})
    assert verdict(res, "exactly one UEFI eMMC Device entry") == "FAIL"
    assert any(f"0 boot entries labelled {LABEL!r}" in ln for ln in res.lines)


# ------------------------------------------------- efivarfs-rw reads the topmost mount (task 5.42)

EFIVARFS_LABEL = "efivarfs mounted read-write"


def efivarfs_run(efivars, options, **kw):
    lines = []
    res = run_check(
        ReadOnlyOps(RecordingOps(script(efivars, **{f"findmnt -no OPTIONS {efivars}": options}))),
        profile_with(["efivarfs-rw"]),
        staging_dir=STAGE,
        efivars_dir=str(efivars),
        out=lines.append,
    )
    return res


def test_a_lower_rw_mount_under_an_ro_overmount_does_not_pass_efivarfs_rw(efivars):
    res = efivarfs_run(efivars, "rw,nosuid,nodev\nro,nosuid,nodev\n")
    assert verdict(res, EFIVARFS_LABEL) == "FAIL"
    assert res.exit_code == 1


def test_the_topmost_mount_decides_efivarfs_rw(efivars):
    res = efivarfs_run(efivars, "ro,nosuid,nodev\nrw,nosuid,nodev\n")
    assert verdict(res, EFIVARFS_LABEL) == "PASS"
    assert res.exit_code == 0


def test_a_single_rw_mount_still_passes_efivarfs_rw(efivars):
    assert verdict(efivarfs_run(efivars, "rw,nosuid,nodev,noexec,relatime\n"), EFIVARFS_LABEL) == "PASS"


@pytest.mark.parametrize("options", ["", "\n", "  \n"])
def test_empty_findmnt_output_is_not_examined_for_efivarfs_rw(efivars, options):
    res = efivarfs_run(efivars, options)
    line = [ln for ln in res.lines if EFIVARFS_LABEL in ln][0]
    assert "not examined" in line, line
    assert res.exit_code == 2 and (res.examined, res.total) == (0, 1)


# ------------------------------------------------- board prerequisites (task 5.37)

PREREQ_LABEL = "board prerequisites"


def prereq_run(efivars, **over):
    lines = []
    ops = ReadOnlyOps(RecordingOps(script(efivars, **over)))
    res = run_check(
        ops,
        profile_with(["board-prerequisites"]),
        staging_dir=STAGE,
        efivars_dir=str(efivars),
        out=lines.append,
    )
    return res, ops._inner


def test_board_prerequisites_pass_with_gnu_tools_and_full_stdlib(efivars):
    res, rec = prereq_run(efivars)
    assert res.exit_code == 0 and (res.examined, res.total) == (1, 1)
    assert verdict(res, PREREQ_LABEL) == "PASS"
    assert [c.line for c in rec.calls if c.kind == "exec"][:3] == [
        "install --version",
        "sha256sum --version",
        "dd --version",
    ]


@pytest.mark.parametrize("tool", ["install", "sha256sum", "dd"])
def test_busybox_style_tool_fails_naming_it_and_only_it(efivars, tool):
    res, _ = prereq_run(efivars, **{f"{tool} --version": BUSYBOX_REFUSAL})
    assert res.exit_code == 1
    assert (res.examined, res.total) == (1, 1)
    line = [ln for ln in res.lines if ln.startswith("FAIL  " + PREREQ_LABEL)][0]
    assert tool in line
    assert all(other not in line for other in {"install", "sha256sum", "dd"} - {tool}), line
    assert "not examined" not in line


def test_a_tool_absent_from_the_board_fails_naming_it(efivars):
    gone = OpFailed(["dd", "--version"], None, "tool 'dd' not found")
    res, _ = prereq_run(efivars, **{"dd --version": gone})
    assert res.exit_code == 1
    assert "dd" in [ln for ln in res.lines if ln.startswith("FAIL  " + PREREQ_LABEL)][0]


def test_all_three_missing_are_all_named(efivars):
    over = {f"{t} --version": BUSYBOX_REFUSAL for t in ("install", "sha256sum", "dd")}
    res, _ = prereq_run(efivars, **over)
    line = [ln for ln in res.lines if ln.startswith("FAIL  " + PREREQ_LABEL)][0]
    assert all(t in line for t in ("install", "sha256sum", "dd")), line


def test_a_busybox_banner_with_rc_zero_is_not_gnu(efivars):
    res, _ = prereq_run(efivars, **{"install --version": "BusyBox v1.36.1 (2024) multi-call binary.\n"})
    assert res.exit_code == 1
    assert "install" in [ln for ln in res.lines if ln.startswith("FAIL  " + PREREQ_LABEL)][0]


def test_the_dd_banner_that_omits_the_word_gnu_still_passes(efivars):
    res, _ = prereq_run(efivars, **{"dd --version": "dd (coreutils) 9.12\n"})
    assert res.exit_code == 0 and verdict(res, PREREQ_LABEL) == "PASS"


@pytest.mark.parametrize(
    "banner",
    [
        "install (uutils coreutils) 0.0.27\n",
        "toybox 0.8.11\n",
        "install (GNU findutils) 4.9\n",
        "something unrecognised\n",
        "",
    ],
    ids=["uutils", "toybox", "gnu-but-not-coreutils", "unrecognised", "empty"],
)
def test_only_a_gnu_coreutils_banner_passes_as_gnu(efivars, banner):
    res, _ = prereq_run(efivars, **{"install --version": banner})
    assert res.exit_code == 1
    line = [ln for ln in res.lines if ln.startswith("FAIL  " + PREREQ_LABEL)][0]
    assert "install" in line and "sha256sum" not in line and "dd" not in line, line


def test_the_prerequisite_check_does_not_import_modules_it_cannot_judge(efivars):
    # The runner imports every module at start-up, so a module loop here could never fail on a board.
    assert not hasattr(cmd_check, "RUNNER_STDLIB")
    assert "importer" not in inspect.signature(run_check).parameters
    res, _ = prereq_run(efivars)
    ok = [ln for ln in res.lines if ln.startswith("PASS  " + PREREQ_LABEL)][0]
    assert "standard-library" not in ok and "module" not in ok, ok
    assert ok == "PASS  board prerequisites: GNU install, sha256sum, dd present"


def test_prerequisites_issue_only_read_vectors_and_call_no_mutating_verb(efivars):
    over = {f"{t} --version": BUSYBOX_REFUSAL for t in ("install", "sha256sum", "dd")}
    for extra in ({}, over):
        res, rec = prereq_run(efivars, **extra)
        execs = [c for c in rec.calls if c.kind == "exec"]
        assert {"install --version", "sha256sum --version", "dd --version"} <= {c.line for c in execs}
        assert not any(vector_mutates(c.vector) for c in execs)


def test_prerequisites_count_in_the_examined_out_of_declared_total(efivars):
    res, _ = run(efivars)
    assert (res.examined, res.total) == (16, 16)
    assert res.lines[-2:] == ["checks: 16/16", "PREFLIGHT PASS"]
    assert verdict(res, PREREQ_LABEL) == "PASS"


def test_failed_prerequisites_still_count_as_examined(efivars):
    res, _ = run(efivars, **{"install --version": BUSYBOX_REFUSAL})
    assert res.exit_code == 1 and (res.examined, res.total) == (16, 16)
    assert f"[{PREREQ_LABEL}]" in res.lines[-1]


# ---- 5.39 (5): the arm needs -n and -N, not -C ----

BOOTNEXT_HELP = "Usage: efibootmgr [options]\n  -n | --bootnext XXXX   set BootNext to XXXX (hex)\n  -N | --delete-bootnext delete BootNext\n"
BOOTNEXT = "efibootmgr-supports-bootnext"
BOOTNEXT_LABEL = "efibootmgr supports -n and -N"


def test_supports_bootnext_passes_when_help_lists_both(efivars):
    res, _ = run(efivars, profile=profile_with([BOOTNEXT]), **{"efibootmgr --help": BOOTNEXT_HELP})
    assert res.exit_code == 0
    assert verdict(res, BOOTNEXT_LABEL) == "PASS"


@pytest.mark.parametrize(
    "help_text",
    ["Usage: efibootmgr\n  -n | --bootnext XXXX  set\n", "Usage: efibootmgr\n  -N | --delete-bootnext x\n", "Usage: efibootmgr [-C]\n"],
)
def test_supports_bootnext_fails_when_either_is_missing(efivars, help_text):
    res, _ = run(efivars, profile=profile_with([BOOTNEXT]), **{"efibootmgr --help": help_text})
    assert res.exit_code == 1
    assert verdict(res, BOOTNEXT_LABEL) == "FAIL"


def test_supports_bootnext_help_failing_is_not_examined(efivars):
    res, rec = run(efivars, profile=profile_with([BOOTNEXT]), **{"efibootmgr --help": OpResult(rc=1)})
    _assert_not_examined(res, rec, BOOTNEXT_LABEL, "efibootmgr --help")


# ---- 5.39 (1): the entry must not precede BootCurrent in BootOrder ----

AFTER = "arm-entry-after-boot-current"
AFTER_LABEL = "UEFI eMMC Device entry does not precede BootCurrent"


def test_entry_before_boot_current_fails_the_check_naming_both(efivars):
    listing = EFI_OK.replace("BootCurrent: 0001", "BootCurrent: 0000").replace(ORDER, "0002,0000,0001")
    res, _ = run(efivars, profile=profile_with([AFTER]), **{"efibootmgr -v": listing})
    assert res.exit_code == 1
    line = [ln for ln in res.lines if AFTER_LABEL in ln][0]
    assert line.startswith("FAIL") and "Boot0002" in line and "BootCurrent 0000" in line


def test_entry_after_boot_current_passes_the_check(efivars):
    res, _ = run(efivars, profile=profile_with([AFTER]))
    assert verdict(res, AFTER_LABEL) == "PASS"


def test_missing_boot_current_is_not_examined_by_the_check(efivars):
    listing = EFI_OK.replace("BootCurrent: 0001\n", "")
    res, rec = run(efivars, profile=profile_with([AFTER]), **{"efibootmgr -v": listing})
    _assert_not_examined(res, rec, AFTER_LABEL, "BootCurrent")


# ---- 5.39 (6): L4TDefaultBootMode is shown, never judged ----

L4T = "L4TDefaultBootMode-781e084c-a330-417c-b678-38e696380cb9"


def test_l4t_default_boot_mode_is_an_info_line_with_its_value(efivars):
    (efivars / L4T).write_bytes(bytes([7, 0, 0, 0, 2, 0, 0, 0]))
    res, _ = run(efivars)
    assert "INFO  L4TDefaultBootMode: 2 (data 02000000)" in res.lines
    assert (res.exit_code, res.examined, res.total) == (0, 16, 16)


def test_l4t_default_boot_mode_absent_reads_unset_and_changes_no_count(efivars):
    res, _ = run(efivars)
    assert "INFO  L4TDefaultBootMode: unset" in res.lines
    assert res.exit_code == 0


def test_a_present_partition_table_names_the_way_out():
    from types import SimpleNamespace

    ops = SimpleNamespace(sfdisk_dump=lambda dev: OpResult(rc=0, stdout=b"label: gpt\n"))
    c = SimpleNamespace(device=DISK, require_device=lambda: None, ops=ops)
    ok, detail = cmd_check._no_partition_table(c)
    assert not ok
    assert "a partition table is present" in detail
    assert "expected after an earlier install" in detail and "wipefs -a" in detail
