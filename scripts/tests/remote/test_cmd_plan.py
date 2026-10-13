"""Tests for the read-only plan subcommand."""

from __future__ import annotations

import hashlib
import json
import pathlib

import devgraph
import pytest

from avocado_flash_remote import cmd_plan, layout
from avocado_flash_remote import profile as prof
from avocado_flash_remote.images import ScanResult
from golden_deviation import kit_to_port_data_size
from avocado_flash_remote.ops import (
    FS_READ_KINDS,
    MutationRefused,
    OpResult,
    ReadOnlyOps,
    RecordingOps,
    vector_mutates,
)

HERE = pathlib.Path(__file__).resolve().parent
PROFILE_PATH = HERE.parent.parent / "avocado_flash_remote" / "profiles" / "jetson-agx-orin-j5012.json"
GOLDEN = HERE / "golden" / "real-board-dry-run.txt"
STAGE = "/run/emmc-test-images"
RUN_DIR = "/var/lib/avocado-flash/runs/r1"
RUN_ID = "run-0001"
MACHINE_ID = "0123456789abcdef0123456789abcdef"
EFI = (
    "BootCurrent: 0001\nTimeout: 5 seconds\nBootOrder: 0001,0002\n"
    "Boot0001* UEFI NVMe\nBoot0002* UEFI eMMC Device\tVenHw(1e5a432c-0000-0000-0000-000000000000)/SD(0)\n"
)

# Deliberate parity deviation (task 5.36): the kit's golden dry run creates a boot entry with
# `efibootmgr -C` and arms the new number. This tool arms the firmware's own storage entry, so
# exactly these golden lines differ. Each maps to the replacement text (None drops the line).
# The golden file is never edited; kit_to_port_arm_lines() asserts every key is still in it.
ARM_DEVIATION = {
    "  create : efibootmgr -C -d /dev/mmcblk0 -p 11 -L avocado-emmc-oneshot -l '\\EFI\\BOOT\\BOOTAA64.EFI' -u 'bootmode=bootimg'":
        "  select : the firmware's existing entry 'UEFI eMMC Device' (Boot0002); no entry is created or deleted",
    "  arm    : efibootmgr -n <new entry number>": "  arm    : efibootmgr -n 0002",
    "DRY-RUN would run: efibootmgr -C -d /dev/mmcblk0 -p 11 -L avocado-emmc-oneshot -l \\\\EFI\\\\BOOT\\\\BOOTAA64.EFI -u bootmode=bootimg": None,
    "DRY-RUN would run: efibootmgr -n NNNN": "DRY-RUN would run: efibootmgr -n 0002",
}


def kit_to_port_arm_lines(golden_lines):
    """The kit golden with only the ARM_DEVIATION lines rewritten to this tool's arm text."""
    missing = [k for k in ARM_DEVIATION if k not in golden_lines]
    assert not missing, f"golden no longer carries the deviating lines: {missing}"
    out = []
    for ln in golden_lines:
        if ln in ARM_DEVIATION:
            if ARM_DEVIATION[ln] is not None:
                out.append(ARM_DEVIATION[ln])
        else:
            out.append(ln)
    return out


BLANK = OpResult(rc=1, stderr="sfdisk: /dev/mmcblk0: does not contain a recognized partition table")


ARG = "module_blacklist=nvme,nvme_core,pcie_tegra194"


def hdr(cmdline="console=ttyS0 " + ARG, extra="", magic=b"ANDROID!", version=0):
    h = bytearray(2048)
    h[0:8] = magic
    h[40:44] = version.to_bytes(4, "little")
    h[64 : 64 + len(cmdline)] = cmdline.encode()
    h[608 : 608 + len(extra)] = extra.encode()
    return bytes(h)


GOOD_HDR = hdr()


def load(data=None):
    raw = PROFILE_PATH.read_bytes() if data is None else data
    return prof.load_profile_bytes(raw), prof.profile_hash(raw)


def sha(text):
    return hashlib.sha256(text.encode()).hexdigest()


def scans_for(profile, sizes=None, zero=()):
    out = {}
    for role, img in profile.images.items():
        size = (sizes or {}).get(role, 4096)
        out[img.file] = ScanResult(size, sha("content-" + img.file), role in zero, (1, 1, size, 1))
    return out


def manifest_text(scans, extra=""):
    return "".join(f"{s.sha256}  {name}\n" for name, s in scans.items()) + extra


def script_for(profile, scans, *, root="/dev/nvme0n1p2", stage_src="tmpfs", mounted="", sfdisk=BLANK,
               lsblk=None, sectors=None, efi=EFI, manifest=None, serial=None):
    dev = profile.target.device
    name = dev.rsplit("/", 1)[-1]
    s = {
        f"blockdev --getsz {dev}": f"{sectors or profile.target.sectors}\n",
        f"lsblk -rn -o NAME,TYPE {dev}": lsblk if lsblk is not None else f"{name} disk\n",
        f"sfdisk --dump {dev}": sfdisk,
        "findmnt -rn -o SOURCE": mounted or "/dev/nvme0n1p2\ntmpfs\n",
        "findmnt -no SOURCE -T /": root + "\n",
        f"findmnt -no SOURCE -T {STAGE}": stage_src + "\n",
        "findmnt -no SOURCE -T /etc/ssh": root + "\n",
        "efibootmgr -v": efi,
        "read_file /etc/machine-id": MACHINE_ID + "\n",
        f"read_file {STAGE}/MANIFEST.hashes": manifest if manifest is not None else manifest_text(scans),
    }
    s.update(devgraph.standard_script())
    if serial:
        s[f"read_file /sys/block/{name}/device/serial"] = serial + "\n"
    return s


class Rec:
    def __init__(self):
        self.calls = []

    def __call__(self, run_dir, name, data):
        self.calls.append((run_dir, name, data))
        return "x"


def plan(profile=None, phash=None, *, script=None, scans=None, ops=None, rec=None, scanner=None, **kw):
    if profile is None:
        profile, phash = load()
    scans = scans if scans is not None else scans_for(profile)
    ops = ops or RecordingOps(script if script is not None else script_for(profile, scans))
    rec = rec if rec is not None else Rec()
    lines = []

    def default_scanner(path):
        name = path.rsplit("/", 1)[-1]
        if name not in scans:
            raise FileNotFoundError(path)
        return scans[name]

    res = cmd_plan.run_plan(
        ops,
        profile,
        phash,
        staging_dir=STAGE,
        run_dir=RUN_DIR,
        record_writer=rec,
        board_identity=None,
        run_id=RUN_ID,
        out=lines.append,
        scanner=scanner or default_scanner,
        now=lambda: "2026-01-01T00:00:00Z",
        **kw,
    )
    assert res.lines == lines
    return res, ops, rec


def assert_clean_refusal(res, ops, rec, *needles):
    assert res.exit_code == 1
    assert res.plan_record is None
    assert rec.calls == []
    assert not any(vector_mutates(c.vector) for c in ops.calls if c.kind == "exec")
    assert not any(c.kind == "fs" and c.vector[0] not in FS_READ_KINDS for c in ops.calls)
    text = "\n".join(res.lines)
    assert "no mutating tool was called" not in text
    for n in needles:
        assert n in text, (n, text)


# ------------------------------------------------------------------ golden


def test_plan_body_matches_real_board_golden_byte_for_byte():
    res, ops, rec = plan()
    assert res.exit_code == 0
    # The header block (profile hash, device identity, plan record path, ...)
    # holds every line this tool adds beyond the kit's dry run; it ends at
    # BODY_MARKER. Everything after the marker is compared byte-for-byte with
    # the golden. Only the golden's trailing harness line DRYRUN-RC= is
    # dropped; the staging dir is the golden's own, and the golden already
    # carries the literal NNNN entry placeholder, so nothing else is normalised.
    marker = res.lines.index(cmd_plan.BODY_MARKER)
    header, body = res.lines[:marker], res.lines[marker + 1 :]
    golden = GOLDEN.read_text().splitlines()
    assert golden[-1].startswith("DRYRUN-RC=")
    # One deliberate difference: the kit stages a file called MANIFEST, the host
    # stages MANIFEST.hashes. Only that exact line is normalised back to the
    # kit's wording; the assertions detect a silent edit of the golden.
    kit_line = f"verifying checksums from {STAGE}/MANIFEST"
    assert golden[0] == kit_line
    assert body[0] == kit_line + ".hashes"
    body = [kit_line] + body[1:]
    # The data partition size is the second deliberate difference: see golden_deviation.
    assert body == kit_to_port_data_size(kit_to_port_arm_lines(golden[:-1]))
    joined = "\n".join(header)
    assert prof.profile_hash(PROFILE_PATH.read_bytes()) in joined
    assert "/dev/mmcblk0" in joined
    assert f"{RUN_DIR}/plan.json" in joined


def test_plan_states_the_exact_efibootmgr_n_and_no_creating_option():
    res, _, _ = plan()
    text = "\n".join(res.lines)
    assert "DRY-RUN would run: efibootmgr -n 0002" in res.lines
    assert "  arm    : efibootmgr -n 0002" in res.lines
    assert "efibootmgr -C" not in text and "-L " not in text and "NNNN" not in text


def test_ends_with_no_mutating_tool_statement():
    res, _, _ = plan()
    assert res.lines[-1] == "dry run complete: no mutating tool was called"


def test_output_is_deterministic_apart_from_header():
    a, _, _ = plan()
    b, _, _ = plan()
    assert a.lines == b.lines


def test_no_mutation_recorded_and_works_under_readonly_ops():
    profile, phash = load()
    scans = scans_for(profile)
    inner = RecordingOps(script_for(profile, scans))
    res, _, rec = plan(ops=ReadOnlyOps(inner))
    assert res.exit_code == 0
    assert not any(vector_mutates(c.vector) for c in inner.calls if c.kind == "exec")
    assert not any(c.kind == "fs" and c.vector[0] not in FS_READ_KINDS for c in inner.calls)
    assert len(rec.calls) == 1


def test_readonly_ops_still_refuses_mutation():
    inner = RecordingOps({})
    with pytest.raises(MutationRefused):
        ReadOnlyOps(inner).sfdisk_write("/dev/mmcblk0", "x")


# ------------------------------------------------------------ plan record


def test_plan_record_fields():
    profile, phash = load()
    scans = scans_for(profile)
    res, _, rec = plan(profile, phash, scans=scans)
    assert len(rec.calls) == 1
    run_dir, name, data = rec.calls[0]
    assert (run_dir, name) == (RUN_DIR, "plan.json")
    assert data == res.plan_record
    json.dumps(data)
    assert data["schema_version"] == 1
    assert data["run_id"] == RUN_ID
    assert data["profile_hash"] == phash
    assert data["board_identity"] == {"machine_id": MACHINE_ID, "device_serial": "unavailable"}
    assert data["image_hashes"] == {r: scans[i.file].sha256 for r, i in profile.images.items()}
    assert data["image_sizes"] == {r: 4096 for r in profile.images}
    expect = layout.sfdisk_input(profile.layout.params, profile.target.device)
    assert data["table_hash"] == sha(expect)
    assert data["arm"]["label"] == "UEFI eMMC Device"
    assert data["arm"]["entry_number"] == "0002"
    assert data["arm"]["preexisting_boot_order"] == "0001,0002"
    assert data["created_utc"] == "2026-01-01T00:00:00Z"


def test_plan_record_names_the_bundle_that_wrote_it_when_the_runner_supplies_the_digest():
    _res, _, rec = plan(bundle_json_sha256="c" * 64)
    assert rec.calls[0][2]["bundle_json_sha256"] == "c" * 64
    assert "bundle_sha256" not in rec.calls[0][2]


def test_plan_record_has_no_bundle_field_without_a_digest():
    _res, _, rec = plan()
    assert "bundle_json_sha256" not in rec.calls[0][2]


def test_device_serial_recorded_when_available():
    profile, phash = load()
    scans = scans_for(profile)
    script = script_for(profile, scans, serial="0xdeadbeef")
    res, _, _ = plan(profile, phash, script=script, scans=scans)
    assert res.plan_record["board_identity"]["device_serial"] == "0xdeadbeef"


def test_record_not_derived_from_time():
    a, _, _ = plan()
    profile, phash = load()
    lines = []
    res = cmd_plan.run_plan(
        RecordingOps(script_for(profile, scans_for(profile))), profile, phash,
        staging_dir=STAGE, run_dir=RUN_DIR, record_writer=Rec(), board_identity=None,
        run_id=RUN_ID, out=lines.append, scanner=lambda p: scans_for(profile)[p.rsplit("/", 1)[-1]],
        now=lambda: "2030-12-31T23:59:59Z",
    )
    r1, r2 = dict(a.plan_record), dict(res.plan_record)
    assert r1.pop("created_utc") != r2.pop("created_utc")
    assert r1 == r2


def test_default_record_writer_writes_plan_json(tmp_path):
    profile, phash = load()
    scans = scans_for(profile)
    ops = RecordingOps(script_for(profile, scans))
    res = cmd_plan.run_plan(
        ops, profile, phash, staging_dir=STAGE, run_dir=str(tmp_path), record_writer=None,
        board_identity=None, run_id=RUN_ID, out=lambda s: None,
        scanner=lambda p: scans[p.rsplit("/", 1)[-1]],
    )
    assert res.exit_code == 0
    on_disk = json.loads((tmp_path / "plan.json").read_text())
    assert on_disk["run_id"] == RUN_ID
    assert on_disk["profile_hash"] == phash


def test_real_scanner_on_real_files(tmp_path):
    profile, phash = load()
    for img in profile.images.values():
        (tmp_path / img.file).write_bytes(b"data-" + img.file.encode())
    files = {i.file for i in profile.images.values()}
    man = "".join(
        f"{hashlib.sha256(b'data-' + f.encode()).hexdigest()}  {f}\n" for f in sorted(files)
    )
    script = script_for(profile, {}, manifest=man)
    script[f"read_file {tmp_path}/MANIFEST.hashes"] = man
    script[f"findmnt -no SOURCE -T {tmp_path}"] = "tmpfs\n"
    ops = RecordingOps(script)
    res = cmd_plan.run_plan(
        ops, profile, phash, staging_dir=str(tmp_path), run_dir=str(tmp_path / "run"),
        record_writer=Rec(), board_identity=None, run_id=RUN_ID, out=lambda s: None,
        file_reader=lambda p: GOOD_HDR,
    )
    assert res.exit_code == 0, res.lines


# --------------------------------------------------------------- refusals


def test_refuses_nvme_target():
    raw = PROFILE_PATH.read_bytes().replace(b'"/dev/mmcblk0"', b'"/dev/nvme0n1"')
    profile, phash = load(raw)
    res, ops, rec = plan(profile, phash)
    assert_clean_refusal(res, ops, rec, "nvme")


def test_refuses_unexpected_device_pattern():
    raw = PROFILE_PATH.read_bytes().replace(b'"/dev/mmcblk0"', b'"/dev/mmcblk0p3"')
    profile, phash = load(raw)
    res, ops, rec = plan(profile, phash)
    assert_clean_refusal(res, ops, rec, "/dev/mmcblk0p3")


@pytest.mark.parametrize("which", ["root", "stage", "ssh"])
def test_refuses_target_backing_running_paths(which):
    profile, phash = load()
    scans = scans_for(profile)
    script = script_for(profile, scans)
    key = {"root": "findmnt -no SOURCE -T /", "stage": f"findmnt -no SOURCE -T {STAGE}",
           "ssh": "findmnt -no SOURCE -T /etc/ssh"}[which]
    script[key] = "/dev/mmcblk0p1\n"
    res, ops, rec = plan(profile, phash, script=script, scans=scans)
    assert_clean_refusal(res, ops, rec, "/dev/mmcblk0")
    assert {"root": "root", "stage": "staging", "ssh": "SSH"}[which] in "\n".join(res.lines)


def test_refuses_mounted_partition_of_target():
    profile, phash = load()
    scans = scans_for(profile)
    script = script_for(profile, scans, mounted="/dev/mmcblk0p16\n")
    res, ops, rec = plan(profile, phash, script=script, scans=scans)
    assert_clean_refusal(res, ops, rec, "mounted")


def test_refuses_existing_partition_table():
    profile, phash = load()
    scans = scans_for(profile)
    dump = OpResult(stdout=b"label: gpt\nlabel-id: AB\n/dev/mmcblk0p1 : start=40, size=8\n")
    script = script_for(profile, scans, sfdisk=dump)
    res, ops, rec = plan(profile, phash, script=script, scans=scans)
    assert_clean_refusal(res, ops, rec, "partition table")


def test_refuses_when_lsblk_shows_partitions():
    profile, phash = load()
    scans = scans_for(profile)
    script = script_for(profile, scans, lsblk="mmcblk0 disk\nmmcblk0p1 part\n")
    res, ops, rec = plan(profile, phash, script=script, scans=scans)
    assert_clean_refusal(res, ops, rec, "1 partition")


def test_refuses_sector_count_mismatch():
    profile, phash = load()
    scans = scans_for(profile)
    script = script_for(profile, scans, sectors=1000)
    res, ops, rec = plan(profile, phash, script=script, scans=scans)
    assert_clean_refusal(res, ops, rec, "1000", str(profile.target.sectors))


def test_refuses_identity_mismatch():
    raw = PROFILE_PATH.read_bytes().replace(b'"value": "mmcblk0"', b'"value": "mmcblk9"')
    profile, phash = load(raw)
    res, ops, rec = plan(profile, phash)
    assert_clean_refusal(res, ops, rec, "identity", "mmcblk9")


BYPATH = "platform-3460000.mmc"
BYPATH_NODE = f"/dev/disk/by-path/{BYPATH}"


def _bypath_profile():
    raw = PROFILE_PATH.read_bytes().replace(
        b'"kind": "sysfs-name"', b'"kind": "by-path"'
    ).replace(b'"value": "mmcblk0"', f'"value": "{BYPATH}"'.encode())
    return load(raw)


def test_by_path_identity_that_resolves_to_the_target_passes():
    profile, phash = _bypath_profile()
    scans = scans_for(profile)
    script = script_for(profile, scans)
    script[f"realpath {BYPATH_NODE}"] = "/dev/mmcblk0\n"
    res, ops, rec = plan(profile, phash, script=script, scans=scans)
    assert res.exit_code == 0, res.lines


@pytest.mark.parametrize("answer", ["/dev/sda\n", "/dev/mmcblk0p1\n", FileNotFoundError("gone"), "/sys/x\n"])
def test_by_path_identity_mismatch_or_absence_refuses(answer):
    profile, phash = _bypath_profile()
    scans = scans_for(profile)
    script = script_for(profile, scans)
    script[f"realpath {BYPATH_NODE}"] = answer
    res, ops, rec = plan(profile, phash, script=script, scans=scans)
    assert_clean_refusal(res, ops, rec, "identity", BYPATH)


def test_by_path_identity_with_a_separator_refuses():
    raw = PROFILE_PATH.read_bytes().replace(b'"kind": "sysfs-name"', b'"kind": "by-path"').replace(
        b'"value": "mmcblk0"', b'"value": "../mmcblk0"'
    )
    profile, phash = load(raw)
    res, ops, rec = plan(profile, phash)
    assert_clean_refusal(res, ops, rec, "identity")


def test_refuses_missing_staged_image():
    profile, phash = load()
    scans = scans_for(profile)
    del scans["boot.img"]
    res, ops, rec = plan(profile, phash, scans=scans, script=script_for(profile, scans_for(profile)))
    assert_clean_refusal(res, ops, rec, "boot.img", "not found")


def test_plan_reads_manifest_hashes_from_staging_and_names_it():
    profile, phash = load()
    res, ops, rec = plan(profile, phash)
    assert res.exit_code == 0, res.lines
    assert f"verifying checksums from {STAGE}/MANIFEST.hashes" in res.lines
    reads = [c.vector for c in ops.calls if c.kind == "fs" and c.vector[0] == "read_file"]
    assert ("read_file", f"{STAGE}/MANIFEST.hashes") in [tuple(v) for v in reads]


def test_refuses_when_only_a_kit_named_manifest_is_staged():
    profile, phash = load()
    scans = scans_for(profile)
    script = script_for(profile, scans)
    script[f"read_file {STAGE}/MANIFEST"] = script.pop(f"read_file {STAGE}/MANIFEST.hashes")
    res, ops, rec = plan(profile, phash, scans=scans, script=script)
    assert_clean_refusal(res, ops, rec, "manifest not found", f"{STAGE}/MANIFEST.hashes")


def test_refuses_missing_manifest_entry():
    profile, phash = load()
    scans = scans_for(profile)
    man = manifest_text({k: v for k, v in scans.items() if k != "boot.img"})
    res, ops, rec = plan(profile, phash, scans=scans, script=script_for(profile, scans, manifest=man))
    assert_clean_refusal(res, ops, rec, "boot.img", "no checksum")


def test_refuses_checksum_mismatch():
    profile, phash = load()
    scans = scans_for(profile)
    man = manifest_text(scans).replace(scans["boot.img"].sha256, "0" * 64)
    res, ops, rec = plan(profile, phash, scans=scans, script=script_for(profile, scans, manifest=man))
    assert_clean_refusal(res, ops, rec, "checksum", "boot.img")


@pytest.mark.parametrize(
    "bad",
    [hdr("root=/dev/x"), hdr(ARG + "y"), hdr("x" + ARG), hdr(version=3), hdr(magic=b"NOTANDRO"), b"ANDROID!"],
    ids=["noarg", "nearmiss-suffix", "nearmiss-prefix", "hdrv3", "nomagic", "short"],
)
def test_refuses_bad_staged_boot_image_before_any_record(bad):
    profile, phash = load()
    res, ops, rec = plan(profile, phash, file_reader=lambda p: bad if p.endswith("boot.img") else GOOD_HDR)
    assert_clean_refusal(res, ops, rec, "plan refused: staged boot image boot.img", "(guard boot-arg)")


def test_staged_boot_image_refusal_wording_for_missing_argument():
    profile, phash = load()
    res, ops, rec = plan(profile, phash, file_reader=lambda p: hdr("root=/dev/x"))
    assert res.lines == [
        f"plan refused: staged boot image boot.img lacks the required argument {ARG} (guard boot-arg)"
    ]


def test_good_staged_boot_image_passes_and_argument_may_sit_in_extra_cmdline():
    profile, phash = load()
    seen = []

    def rd(p):
        seen.append(p)
        return hdr("quiet", extra=ARG)

    res, ops, rec = plan(profile, phash, file_reader=rd)
    assert res.exit_code == 0
    assert seen == [f"{STAGE}/boot.img", f"{STAGE}/boot.img"]


def test_guard_none_checks_no_staged_image():
    doc = json.loads(PROFILE_PATH.read_bytes())
    doc["guard"] = {"strategy": "none", "params": {}}
    raw = json.dumps(doc).encode()
    profile, phash = load(raw)

    def rd(p):
        raise AssertionError("must not read")

    res, ops, rec = plan(profile, phash, file_reader=rd)
    assert res.exit_code == 0


def test_refuses_when_guard_partition_has_no_image():
    doc = json.loads(PROFILE_PATH.read_bytes())
    del doc["images"]["boot"]
    profile, phash = load(json.dumps(doc).encode())
    scans = scans_for(profile)
    res, ops, rec = plan(profile, phash, scans=scans, script=script_for(profile, scans))
    assert_clean_refusal(res, ops, rec, "A_kernel", "no image")


def test_refuses_zero_filled_var_naming_the_image():
    profile, phash = load()
    scans = scans_for(profile, zero=("var",))
    res, ops, rec = plan(profile, phash, scans=scans)
    assert_clean_refusal(res, ops, rec, "var", "avocado-image-var-jetson-agx-orin-devkit.btrfs", "all zero")


def test_refuses_oversize_image_with_both_sizes():
    profile, phash = load()
    limit = profile.images["dtb"].max_bytes
    scans = scans_for(profile, sizes={"dtb": limit + 1, "dtb_b": limit + 1})
    res, ops, rec = plan(profile, phash, scans=scans)
    assert_clean_refusal(
        res, ops, rec,
        f"image dtb {profile.images['dtb'].file} is {limit + 1} bytes, limit {limit}",
    )


def test_refuses_when_arm_prepare_refuses():
    profile, phash = load()
    scans = scans_for(profile)
    script = script_for(profile, scans, efi=EFI + "BootNext: 0002\n")
    res, ops, rec = plan(profile, phash, script=script, scans=scans)
    assert_clean_refusal(res, ops, rec, "BootNext")


# ----------------------------------------------------- device node naming


def test_non_trailing_p_device_naming():
    raw = (
        PROFILE_PATH.read_bytes()
        .replace(b"/dev/mmcblk0", b"/dev/sdb")
        .replace(b'"value": "mmcblk0"', b'"value": "sdb"')
    )
    profile, phash = load(raw)
    scans = scans_for(profile)
    script = script_for(profile, scans)
    script.update(devgraph.standard().disk("sdb", sysnode="/sys/devices/virtual/block/sdb").script())
    script["sfdisk --dump /dev/sdb"] = OpResult(rc=1, stderr="does not contain a recognized partition table")
    res, ops, rec = plan(profile, phash, script=script, scans=scans)
    assert res.exit_code == 0, res.lines
    text = "\n".join(res.lines)
    assert "/dev/sdb3 " in text and "/dev/sdbp3" not in text
    assert "DRY-RUN would run: sfdisk /dev/sdb" in text
    expect = layout.sfdisk_input(profile.layout.params, "/dev/sdb")
    assert res.plan_record["table_hash"] == sha(expect)


# ---- 5.17: serial identity pinned by a board-support extension -----------------------

PINNED = "0x0badc0de"


def serial_profile_bytes():
    doc = json.loads(PROFILE_PATH.read_text())
    doc["target"]["identity"] = {"kind": "serial", "value": PINNED, "sysfs_attr": "serial"}
    return json.dumps(doc).encode()


def test_matching_pinned_serial_plans_and_records_it():
    profile, phash = load(serial_profile_bytes())
    scans = scans_for(profile)
    res, ops, rec = plan(profile, phash, script=script_for(profile, scans, serial=PINNED), scans=scans)
    assert res.exit_code == 0, res.lines
    assert res.plan_record["board_identity"]["device_serial"] == PINNED


def test_different_serial_refuses_the_plan():
    profile, phash = load(serial_profile_bytes())
    scans = scans_for(profile)
    res, ops, rec = plan(profile, phash, script=script_for(profile, scans, serial="0x00000001"), scans=scans)
    assert_clean_refusal(res, ops, rec, "identity mismatch", "0x00000001")


def test_missing_serial_attribute_refuses_the_plan():
    profile, phash = load(serial_profile_bytes())
    scans = scans_for(profile)
    res, ops, rec = plan(profile, phash, script=script_for(profile, scans), scans=scans)
    assert_clean_refusal(res, ops, rec, "cannot be verified")


# ---- 5.39 (1): plan refuses an entry that precedes BootCurrent in BootOrder ----


def test_plan_refuses_an_entry_that_precedes_boot_current_naming_both_and_the_order():
    profile, phash = load()
    scans = scans_for(profile)
    efi = EFI.replace("BootOrder: 0001,0002", "BootOrder: 0002,0001")
    res, ops, rec = plan(profile, phash, script=script_for(profile, scans, efi=efi), scans=scans)
    assert_clean_refusal(res, ops, rec, "arm pre-flight refused", "Boot0002", "BootCurrent 0001", "0002,0001")


# ---- 5.39 (4): the arm section follows the strategy, not the name of an image role ----


def test_a_uefi_bootnext_profile_without_an_esp_role_still_shows_the_arm_line():
    doc = json.loads(PROFILE_PATH.read_bytes())
    doc["images"]["efi_system"] = doc["images"].pop("esp")
    profile, phash = load(json.dumps(doc).encode())
    res, _, _ = plan(profile, phash)
    assert res.exit_code == 0, res.lines
    assert "  arm    : efibootmgr -n 0002" in res.lines
    assert "DRY-RUN would run: efibootmgr -n 0002" in res.lines


def test_plan_refuses_an_arming_profile_that_maps_no_image_to_an_esp():
    profile, phash = load()
    for part in profile.layout.params["table"]:
        if part["type_guid"].upper() == "C12A7328-F81F-11D2-BA4B-00A0C93EC93B":
            part["type_guid"] = "0FC63DAF-8483-4772-8E79-3D69D8477DE4"
    res, ops, rec = plan(profile, phash)
    assert_clean_refusal(res, ops, rec, "EFI System Partition")


def test_a_disk_with_partitions_is_refused_and_the_refusal_names_the_way_out():
    from types import SimpleNamespace

    from avocado_flash_remote import cmd_plan

    ops = SimpleNamespace(lsblk=lambda dev, cols, check=False: OpResult(rc=0, stdout=b"mmcblk0 disk\nmmcblk0p1 part\nmmcblk0p2 part\n"))
    profile = SimpleNamespace(target=SimpleNamespace(device="/dev/mmcblk0"))
    with pytest.raises(cmd_plan._Refusal) as err:
        cmd_plan._check_empty(ops, profile)
    text = str(err.value)
    assert "lsblk shows 2 partition(s) on /dev/mmcblk0; refusing a disk that is not empty" in text
    assert "expected after an earlier install" in text and "wipefs -a" in text and "plan again" in text
