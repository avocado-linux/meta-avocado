"""Tests for the explicit-table layout and its sfdisk input."""

import copy
import pathlib
import re

import pytest

from avocado_flash_remote import layout
from avocado_flash_remote.layout import LayoutError, check_fits, partition_node, sfdisk_input

GOLDEN = pathlib.Path(__file__).parent / "golden" / "real-board-dry-run.txt"
DEVICE_SECTORS = 122314752
DATA_UUID = "4D21B016-B534-45C2-A9FB-5C16E091FD2D"

_ROW = re.compile(r"^\s+/dev/mmcblk0p(\d+)\s+(\S+)\s+start=(\d+)\s+size=(\d+)\s+type=(\S+)$")


def golden_table():
    section = GOLDEN.read_text().split("== images to write ==")[0]
    parts = []
    for line in section.splitlines():
        m = _ROW.match(line)
        if m:
            parts.append(
                {
                    "number": int(m.group(1)),
                    "name": m.group(2),
                    "start": int(m.group(3)),
                    "size": int(m.group(4)),
                    "type_guid": m.group(5),
                }
            )
    return parts


def golden_sfdisk_text():
    lines = GOLDEN.read_text().splitlines()
    i = lines.index("  would create the table from this sfdisk input:")
    block = []
    for line in lines[i + 1 :]:
        if not line.startswith("    "):
            break
        block.append(line[4:])
    return "\n".join(block) + "\n"


def params():
    return {
        "sector_size": 512,
        "first_lba": 40,
        "last_lba": DEVICE_SECTORS - 34,
        "device_sectors": DEVICE_SECTORS,
        "table": golden_table(),
    }


UUIDS = {16: DATA_UUID}


def test_golden_has_sixteen_partitions():
    assert len(golden_table()) == 16


def test_sfdisk_input_matches_golden_byte_for_byte():
    assert sfdisk_input(params(), "/dev/mmcblk0", uuids=UUIDS) == golden_sfdisk_text()


def test_per_partition_uuid_field_equals_uuids_argument():
    p = params()
    for part in p["table"]:
        if part["number"] == 16:
            part["uuid"] = DATA_UUID
    assert sfdisk_input(p, "/dev/mmcblk0") == golden_sfdisk_text()


def test_deterministic():
    assert sfdisk_input(params(), "/dev/mmcblk0", uuids=UUIDS) == sfdisk_input(
        params(), "/dev/mmcblk0", uuids=UUIDS
    )


def test_order_is_by_start_not_number():
    p = params()
    p["table"].reverse()
    assert sfdisk_input(p, "/dev/mmcblk0", uuids=UUIDS) == golden_sfdisk_text()


def test_no_indentation_and_trailing_newline():
    text = sfdisk_input(params(), "/dev/mmcblk0", uuids=UUIDS)
    assert text.endswith("\n")
    assert all(not l.startswith(" ") for l in text.splitlines())


def test_header_uses_params():
    p = params()
    p["sector_size"] = 4096
    assert "sector-size: 4096\n" in sfdisk_input(p, "/dev/mmcblk0")


@pytest.mark.parametrize(
    "dev,n,expected",
    [
        ("/dev/mmcblk0", 3, "/dev/mmcblk0p3"),
        ("/dev/nvme0n1", 2, "/dev/nvme0n1p2"),
        ("/dev/sdb", 3, "/dev/sdb3"),
        ("/dev/vda", 12, "/dev/vda12"),
    ],
)
def test_partition_node(dev, n, expected):
    assert partition_node(dev, n) == expected


def test_sdb_naming_in_text():
    text = sfdisk_input(params(), "/dev/sdb")
    assert '/dev/sdb3 : start=40, size=262144,' in text
    assert "/dev/sdbp" not in text


def test_overlap_refused():
    p = params()
    p["table"][1]["start"] = p["table"][0]["start"] + 10
    with pytest.raises(LayoutError, match="overlap"):
        sfdisk_input(p, "/dev/mmcblk0")
    with pytest.raises(LayoutError, match="overlap"):
        check_fits(p, DEVICE_SECTORS)


def test_table_exceeding_device_refused():
    p = params()
    p["table"][-1]["size"] += 1
    with pytest.raises(LayoutError, match="last_lba"):
        check_fits(p, DEVICE_SECTORS)
    with pytest.raises(LayoutError):
        sfdisk_input(p, "/dev/mmcblk0")


def test_device_smaller_than_table_refused():
    with pytest.raises(LayoutError):
        check_fits(params(), DEVICE_SECTORS - 1000)


def test_wrong_last_lba_refused():
    p = params()
    p["last_lba"] -= 1
    with pytest.raises(LayoutError, match="last_lba"):
        check_fits(p, DEVICE_SECTORS)


def test_partition_before_first_lba_refused():
    p = params()
    p["table"][0]["start"] = 8
    with pytest.raises(LayoutError, match="first_lba"):
        check_fits(p, DEVICE_SECTORS)


def test_valid_fits():
    check_fits(params(), DEVICE_SECTORS)


def test_does_not_mutate_input():
    p = params()
    before = copy.deepcopy(p)
    sfdisk_input(p, "/dev/mmcblk0", uuids=UUIDS)
    assert p == before


def test_unknown_uuid_number_refused():
    with pytest.raises(LayoutError, match="uuid"):
        sfdisk_input(params(), "/dev/mmcblk0", uuids={99: DATA_UUID})


def test_sfdisk_input_uses_device_sectors_not_last_lba_for_the_size():
    p = params()
    p["device_sectors"] = DEVICE_SECTORS + 1
    with pytest.raises(LayoutError, match="last_lba"):
        sfdisk_input(p, "/dev/mmcblk0")


def test_sfdisk_input_without_device_sectors_refuses():
    p = params()
    del p["device_sectors"]
    with pytest.raises(LayoutError, match="device_sectors"):
        sfdisk_input(p, "/dev/mmcblk0")


@pytest.mark.parametrize("bad", [0, -1, "20480", True, None])
def test_sfdisk_input_with_a_bad_device_sectors_refuses(bad):
    p = params()
    p["device_sectors"] = bad
    with pytest.raises(LayoutError):
        sfdisk_input(p, "/dev/mmcblk0")
