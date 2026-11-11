"""The staged env file is sourced by bash, so only a plain column-0 assignment is read."""

import pytest

from avocado_tegraflash import EngineError
from avocado_tegraflash.plainenv import read_plain_env


def read(tmp_path, text):
    path = tmp_path / ".env.initrd-flash"
    path.write_text(text)
    return read_plain_env(path)


def test_plain_assignments_are_read_with_quotes_removed(tmp_path):
    env = read(tmp_path, 'ROOTFS_IMAGE="r.img"\nROOTFS_DEVICE=nvme0n1\nDATAFILE=\'v.img\'\nOTHER=1\n')
    assert env == {"ROOTFS_IMAGE": "r.img", "ROOTFS_DEVICE": "nvme0n1", "DATAFILE": "v.img"}


def test_the_last_plain_assignment_wins(tmp_path):
    assert read(tmp_path, "ROOTFS_IMAGE=a.img\nROOTFS_IMAGE=b.img\n") == {"ROOTFS_IMAGE": "b.img"}


def test_absent_keys_are_absent_from_the_result(tmp_path):
    assert read(tmp_path, "BOOTDEV=x\n") == {}


def test_a_similarly_named_variable_is_not_the_key(tmp_path):
    assert read(tmp_path, "MY_ROOTFS_IMAGE=a\nROOTFS_IMAGE_X=b\nDATAFILE_B=c\n") == {}


def test_a_comment_mentioning_a_key_is_not_an_assignment(tmp_path):
    assert read(tmp_path, "# ROOTFS_IMAGE=a.img\n  # export ROOTFS_DEVICE=x\n") == {}


@pytest.mark.parametrize(
    "line",
    [
        ' ROOTFS_IMAGE="big.img"',
        "\tROOTFS_IMAGE=big.img",
        'export ROOTFS_IMAGE="big.img"',
        "declare -x ROOTFS_IMAGE=big.img",
        "local ROOTFS_IMAGE=big.img",
        "readonly ROOTFS_IMAGE=big.img",
        "ROOTFS_IMAGE+=big.img",
        "ROOTFS_IMAGE =big.img",
        "X=1; ROOTFS_IMAGE=big.img",
        "true && ROOTFS_IMAGE=big.img",
        "false || ROOTFS_IMAGE=big.img",
        "X=1 ; ROOTFS_IMAGE=big.img",
        "ROOTFS_IMAGE=a.img; ROOTFS_IMAGE=big.img",
        "(ROOTFS_IMAGE=big.img)",
    ],
)
def test_a_non_plain_assignment_is_refused_naming_file_line_and_key(tmp_path, line):
    path = tmp_path / ".env.initrd-flash"
    path.write_text(f"BOOTDEV=x\n{line}\n")
    with pytest.raises(EngineError) as exc:
        read_plain_env(path)
    msg = str(exc.value)
    assert str(path) in msg and ":2" in msg and "ROOTFS_IMAGE" in msg
    assert "sources" in msg and "bash" in msg and "column 0" in msg


@pytest.mark.parametrize("key", ["ROOTFS_DEVICE", "DATAFILE"])
def test_every_guarded_key_is_scanned(tmp_path, key):
    with pytest.raises(EngineError, match=key):
        read(tmp_path, f"export {key}=x\n")


def test_a_non_plain_line_after_a_plain_one_is_still_refused(tmp_path):
    with pytest.raises(EngineError, match=r":2"):
        read(tmp_path, "ROOTFS_IMAGE=a.img\nexport ROOTFS_IMAGE=b.img\n")


def test_line_numbers_count_newlines_only(tmp_path):
    with pytest.raises(EngineError, match=r":3"):
        read(tmp_path, "A=1\x0cB=2\nC=3\n  ROOTFS_IMAGE=x\n")
