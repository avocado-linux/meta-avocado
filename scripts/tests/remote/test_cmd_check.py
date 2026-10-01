"""Tests for the read-only ``check`` subcommand (pre-flight)."""

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
LABEL = "avocado-emmc-oneshot"
EFI_OK = (
    "BootCurrent: 0001\n"
    "Timeout: 5 seconds\n"
    f"BootOrder: {ORDER}\n"
    "Boot0000* UEFI Shell\n"
    "Boot0001* UEFI NVMe\n"
)
MANIFEST = "".join(f"{'a' * 64}  img{i}.bin\n" for i in range(5))
MIN_KIB = 716800


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
        "efibootmgr --help": "Usage: efibootmgr [-c|-C] [-d DISK]\n  -C | --create-only\n",
        "efibootmgr -v": EFI_OK,
        f"findmnt -no OPTIONS {efivars}": "rw,nosuid,nodev,noexec,relatime\n",
        f"read_file {STAGE}/MANIFEST.hashes": MANIFEST,
        "sha256sum --strict -c MANIFEST.hashes": "".join(f"img{i}.bin: OK\n" for i in range(5)),
        f"df -Pk {STAGE}": f"Filesystem 1K-blocks Used Available Use% Mounted on\ntmpfs 100 1 12156576 1% {STAGE}\n",
        f"findmnt -no FSTYPE -T {STAGE}": "tmpfs\n",
        "uname -r": "5.15.148-tegra\n",
        "docker ps -q": "a\nb\nc\n",
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
    "PASS  efibootmgr supports -C: -C listed in --help",
    "PASS  BootOrder unchanged: actual '0001,0002,0000,0003,0004' (expected 0001,0002,0000,0003,0004)",
    "PASS  BootNext unset: unset",
    "PASS  no stale avocado-emmc-oneshot entry: none",
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
    assert res.lines[-2:] == ["checks: 14/14", "PREFLIGHT PASS"]
    assert (res.exit_code, res.examined, res.total) == (0, 14, 14)
    assert not any(vector_mutates(c.vector) for c in rec.calls if c.kind == "exec")


def test_info_lines_not_counted(efivars):
    res, _ = run(efivars)
    assert res.total == 14
    assert sum(ln.startswith(("PASS", "FAIL")) for ln in res.lines) == 14


FAULTS = [
    ("eMMC device exists", {f"lsblk -rn -o TYPE {DISK}": OpResult(rc=32, stderr="not a block device")}),
    ("eMMC not read-only", {f"blockdev --getro {DISK}": "1\n"}),
    ("eMMC sector count", {f"blockdev --getsz {DISK}": "122314751\n"}),
    ("eMMC has no partition table", {f"sfdisk --dump {DISK}": "label: gpt\n"}),
    ("eMMC not mounted", {"findmnt -rn -o SOURCE": "/dev/mmcblk0p1\n"}),
    ("efibootmgr supports -C", {"efibootmgr --help": "Usage: efibootmgr [-c]\n"}),
    ("BootOrder unchanged", {"efibootmgr -v": EFI_OK.replace(ORDER, "0001,0000")}),
    ("BootNext unset", {"efibootmgr -v": "BootNext: 0005\n" + EFI_OK}),
    ("no stale avocado-emmc-oneshot entry", {"efibootmgr -v": EFI_OK + f"Boot0005* {LABEL}\tHD(1)\n"}),
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
        assert res.examined == 14 and res.total == 14


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
    assert verdict(res, "efibootmgr supports -C") == "FAIL"
    line = [ln for ln in res.lines if "efibootmgr supports -C" in ln][0]
    assert "not examined" in line
    assert res.lines[-2:][0] == "checks: 13/14"
    assert res.exit_code == 2
    assert res.examined == 13 and res.total == 14
    assert res.lines[-1].startswith("PREFLIGHT FAIL:")


def test_fail_beats_not_examined_for_exit_code(efivars):
    rec = RecordingOps(script(efivars, **{f"blockdev --getro {DISK}": "1\n"}))
    del rec.script["efibootmgr --help"]
    res, _ = run(efivars, ops=rec)
    assert res.exit_code == 1
    assert res.lines[-2] == "checks: 13/14"


def test_efibootmgr_list_failure_not_examines_dependents(efivars):
    res, _ = run(efivars, **{"efibootmgr -v": OpFailed(["efibootmgr", "-v"], 1, "no efi")})
    assert res.exit_code == 2
    assert res.examined == 11
    assert res.lines[-2] == "checks: 11/14"


def test_missing_manifest_not_examined(efivars):
    rec = RecordingOps(script(efivars))
    del rec.script[f"read_file {STAGE}/MANIFEST.hashes"]
    res, _ = run(efivars, ops=rec)
    assert res.exit_code == 2
    assert res.examined == 13  # checksums run sha256sum, which reads the manifest itself


def test_device_absent_makes_dependents_not_examined(efivars):
    res, _ = run(efivars, **{f"lsblk -rn -o TYPE {DISK}": OpResult(rc=32)})
    assert res.exit_code == 1
    assert verdict(res, "eMMC device exists") == "FAIL"
    assert res.examined == 10 and res.total == 14


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
    assert res.examined == 13


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
    assert res.exit_code == 0 and res.total == 14


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
    res, rec = run(efivars, profile=profile_with(["efibootmgr-supports-create"]), **over)
    _assert_not_examined(res, rec, "efibootmgr supports -C", "efibootmgr --help")


def test_efibootmgr_help_without_dash_c_is_still_a_verdict(efivars):
    over = {"efibootmgr --help": "Usage: efibootmgr [-c]\n"}
    res, _ = run(efivars, profile=profile_with(["efibootmgr-supports-create"]), **over)
    assert res.exit_code == 1
    assert verdict(res, "efibootmgr supports -C") == "FAIL"
    assert not any("not examined" in ln for ln in res.lines)
