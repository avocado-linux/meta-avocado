"""The two shipped profiles load through the closed loader and match the kit."""

import json
import pathlib
import re

import pytest

from avocado_flash_remote import profile as prof

HERE = pathlib.Path(__file__).resolve().parent
PROFILES = HERE.parent.parent / "avocado_flash_remote" / "profiles"
GOLDEN = HERE / "golden" / "real-board-dry-run.txt"

KIT_CHECKS = (
    "emmc-exists",
    "emmc-not-read-only",
    "emmc-sector-count",
    "emmc-no-partition-table",
    "emmc-not-mounted",
    "efibootmgr-supports-bootnext",
    "boot-order-unchanged",
    "boot-next-unset",
    "arm-entry-unique",
    "efivarfs-rw",
    "secure-boot-disabled",
    "staged-images-present",
    "staged-image-checksums",
    "staging-space-free",
)

_ROW = re.compile(
    r"^\s+/dev/mmcblk0p(\d+)\s+(\S+)\s+start=(\d+)\s+size=(\d+)\s+type=([0-9A-F-]{36})\s*$"
)


def _load(name):
    return prof.load_profile_bytes((PROFILES / name).read_bytes())


def _golden_table():
    rows = []
    in_block = False
    for line in GOLDEN.read_text().splitlines():
        if line.startswith("== partitions to create"):
            in_block = True
            continue
        if in_block and line.startswith("=="):
            break
        m = _ROW.match(line)
        if in_block and m:
            n, name, start, size, guid = m.groups()
            rows.append(
                {
                    "number": int(n),
                    "name": name,
                    "start": int(start),
                    "size": int(size),
                    "type_guid": guid,
                }
            )
    return rows


@pytest.fixture(scope="module")
def jetson():
    return _load("jetson-agx-orin-j5012.json")


@pytest.fixture(scope="module")
def fixture_profile():
    return _load("fixture-none.json")


def test_golden_block_parsed():
    assert len(_golden_table()) == 16


def test_jetson_loads(jetson):
    assert jetson.board == "jetson-agx-orin-j5012"
    assert jetson.schema_version == 1


def test_jetson_table_equals_golden(jetson):
    table = list(jetson.layout.params["table"])
    carried = {r["number"]: r["uuid"] for r in table if "uuid" in r}
    assert carried == {16: "4D21B016-B534-45C2-A9FB-5C16E091FD2D"}
    stripped = [{k: v for k, v in r.items() if k != "uuid"} for r in table]
    assert stripped == _golden_table()
    assert jetson.layout.params["first_lba"] == 40
    assert jetson.layout.params["last_lba"] == 122314718
    assert jetson.layout.params["device_sectors"] == 122314752
    assert jetson.layout.params["sector_size"] == 512


def test_jetson_target(jetson):
    t = jetson.target
    assert (t.device, t.sector_size, t.sectors, t.require_empty) == (
        "/dev/mmcblk0",
        512,
        122314752,
        True,
    )
    assert t.identity.kind in ("by-path", "serial", "sysfs-name")


def test_jetson_image_limits_equal_kit(jetson):
    limits = {r: i.max_bytes for r, i in jetson.images.items()}
    assert limits["rootfs"] == 268435456
    assert limits["var"] == 60946071040
    assert limits["boot"] == limits["boot_b"] == 134217728
    assert limits["esp"] == 67108864
    assert limits["dtb"] == limits["dtb_b"] == 786432


def test_jetson_images_map_to_golden_partitions(jetson):
    parts = {
        r: i.partition for r, i in jetson.images.items()
    }
    assert parts == {
        "boot": 3,
        "dtb": 4,
        "boot_b": 6,
        "dtb_b": 7,
        "esp": 11,
        "rootfs": 1,
        "var": 16,
    }


def test_jetson_var_must_be_populated(jetson):
    assert jetson.images["var"].must_be_populated is True
    assert all(i.must_be_populated for i in jetson.images.values())


def test_jetson_arm_guard(jetson):
    assert jetson.arm.strategy == "uefi-bootnext"
    assert jetson.arm.params == {"entry_label": "UEFI eMMC Device"}
    assert jetson.guard.strategy == "boot-arg"
    assert jetson.guard.params["argument"] == "module_blacklist=nvme,nvme_core,pcie_tegra194"
    names = {p["name"] for p in jetson.layout.params["table"]}
    assert set(jetson.guard.params["partitions"]) == {"A_kernel", "B_kernel"} <= names


def test_jetson_checks_are_the_kits_fourteen_plus_board_prerequisites(jetson):
    assert len(jetson.checks) == 16
    assert len(set(jetson.checks)) == 16
    assert [c for c in jetson.checks if c in KIT_CHECKS] == list(KIT_CHECKS)
    assert [c for c in jetson.checks if c not in KIT_CHECKS] == ["arm-entry-after-boot-current", "board-prerequisites"]
    # The exact set, in profile order: a swapped, renamed or dropped check changes it, which the counts above would not.
    assert tuple(jetson.checks) == (
        "emmc-exists",
        "emmc-not-read-only",
        "emmc-sector-count",
        "emmc-no-partition-table",
        "emmc-not-mounted",
        "efibootmgr-supports-bootnext",
        "boot-order-unchanged",
        "boot-next-unset",
        "arm-entry-unique",
        "arm-entry-after-boot-current",
        "efivarfs-rw",
        "secure-boot-disabled",
        "staged-images-present",
        "staged-image-checksums",
        "staging-space-free",
        "board-prerequisites",
    )


@pytest.mark.parametrize("name", ["jetson-agx-orin-j5012.json", "fixture-none.json"])
def test_every_shipped_profile_lists_the_board_prerequisites_check(name):
    assert "board-prerequisites" in _load(name).checks


def test_jetson_staging_and_state(jetson):
    assert jetson.staging.dir == "/run/emmc-test-images"
    assert jetson.staging.min_free_kib == 716800
    assert jetson.state_dir == "/var/lib/avocado-flash"


def test_fixture_loads_and_is_generic(fixture_profile):
    p = fixture_profile
    assert p.board == "fixture-none"
    assert p.arm.strategy == "none"
    assert p.guard.strategy == "none"
    assert p.target.sectors == 20480
    assert p.layout.params["last_lba"] == 20480 - 34
    assert p.checks
    assert p.images


@pytest.mark.parametrize("name", ["jetson-agx-orin-j5012.json", "fixture-none.json"])
def test_profile_json_has_no_duplicate_keys(name):
    # The loader rejects duplicates at any depth; a clean load proves none.
    prof.load_profile_bytes((PROFILES / name).read_bytes())


def test_shipped_jetson_profile_is_generic_and_pins_no_hardware_serial(jetson):
    # A hardware serial identifies one board: it belongs in a board-support
    # extension profile, never in the shipped generic profile.
    assert jetson.target.identity.kind != "serial"
    raw = (PROFILES / "jetson-agx-orin-j5012.json").read_text()
    assert not re.search(r"0x[0-9a-fA-F]{6,}", raw)
    assert "extension" in jetson.description.lower() and "serial" in jetson.description.lower()


def _with_identity(identity, *, check=True):
    doc = json.loads((PROFILES / "jetson-agx-orin-j5012.json").read_bytes())
    doc["target"]["identity"] = identity
    doc["checks"] = [c for c in doc["checks"] if c != "target-identity"] + (["target-identity"] if check else [])
    return prof.load_profile_bytes(json.dumps(doc).encode())


def test_shipped_jetson_identity_is_name_only_so_write_must_refuse(jetson):
    problem = prof.write_identity_problem(jetson)
    assert problem is not None
    assert "target-identity" in problem and "serial" in problem and "by-path" in problem


def test_fixture_profile_identity_is_good_enough_to_write(fixture_profile):
    assert prof.write_identity_problem(fixture_profile) is None


@pytest.mark.parametrize(
    "identity,check,refused",
    [
        ({"kind": "sysfs-name", "value": "mmcblk0"}, True, True),
        ({"kind": "serial", "value": "0x0badc0de", "sysfs_attr": "serial"}, False, True),
        ({"kind": "serial", "value": "0x0badc0de", "sysfs_attr": "serial"}, True, False),
        ({"kind": "serial", "value": "0x0badc0de"}, True, False),
        ({"kind": "by-path", "value": "platform-x.mmc"}, True, False),
        ({"kind": "by-path", "value": "platform-x.mmc"}, False, True),
        ({"kind": "sysfs-name", "value": "mmcblk0", "sysfs_attr": "serial"}, True, True),
        ({"kind": "sysfs-name", "value": "mmcblk9"}, True, False),
    ],
)
def test_write_identity_gate_cases(identity, check, refused):
    problem = prof.write_identity_problem(_with_identity(identity, check=check))
    assert (problem is not None) is refused, problem
