"""Tests for host-side profile resolution, printing and hashing."""

import json
import os

import pytest

from avocado_flash_remote import profile_resolve as pr
from avocado_flash_remote.profile import ProfileError, load_profile_bytes, profile_hash

DEVICE_SECTORS = 122314752
EFI = "C12A7328-F81F-11D2-BA4B-00A0C93EC93B"
LINUX = "0FC63DAF-8483-4772-8E79-3D69D8477DE4"


def base(board="example-board", description="an example"):
    return {
        "schema_version": 1,
        "board": board,
        "description": description,
        "target": {
            "device": "/dev/mmcblk*",
            "sector_size": 512,
            "sectors": DEVICE_SECTORS,
            "require_empty": False,
            "identity": {"kind": "by-path", "value": "platform-example-mmc"},
        },
        "layout": {
            "strategy": "explicit-table",
            "params": {
                "sector_size": 512,
                "first_lba": 34,
                "last_lba": DEVICE_SECTORS - 34,
                "device_sectors": DEVICE_SECTORS,
                "table": [
                    {"number": 1, "name": "boot", "start": 2048, "size": 262144,
                     "type_guid": EFI},
                    {"number": 2, "name": "root-a", "start": 264192, "size": 1048576,
                     "type_guid": LINUX},
                    {"number": 3, "name": "var", "start": 1312768, "size": 1048576,
                     "type_guid": LINUX},
                ],
            },
        },
        "images": {
            "boot": {"partition": 1, "max_bytes": 134217728,
                     "must_be_populated": True, "file": "boot.img"},
            "root": {"partition": 2, "max_bytes": 536870912,
                     "must_be_populated": True, "file": "root.img"},
        },
        "checks": ["device-identity", "device-empty"],
        "arm": {"strategy": "uefi-bootnext",
                "params": {"entry_label": "UEFI eMMC Device"}},
        "guard": {"strategy": "boot-arg",
                  "params": {"argument": "avocado.flash=1", "partitions": ["boot"]}},
        "staging": {"dir": "/var/tmp/avocado-flash", "min_free_kib": 1048576},
        "state_dir": "/var/lib/avocado-flash",
    }


def put(directory, board="example-board", doc=None, indent=None, name=None):
    directory.mkdir(parents=True, exist_ok=True)
    data = json.dumps(doc or base(board), indent=indent).encode()
    path = directory / ((name or board) + ".json")
    path.write_bytes(data)
    return path, data


@pytest.fixture
def dirs(tmp_path):
    return tmp_path / "ext", tmp_path / "shipped"


class Exploding:
    """A directory stand-in that fails any filesystem access."""

    def __getattr__(self, name):
        raise AssertionError(f"filesystem access: {name}")

    def __truediv__(self, other):
        raise AssertionError("filesystem access: /")

    def __fspath__(self):
        raise AssertionError("filesystem access: fspath")


def test_extension_overrides_shipped(dirs):
    ext, shipped = dirs
    ext_path, ext_data = put(ext, doc=base(description="ext"))
    ship_path, _ = put(shipped)
    r = pr.resolve_profile("example-board", ext, shipped)
    assert r.source == "extension"
    assert r.path == ext_path
    assert r.other_path == ship_path
    assert r.data == ext_data
    assert r.profile.description == "ext"


def test_only_shipped(dirs):
    ext, shipped = dirs
    ext.mkdir()
    ship_path, data = put(shipped)
    r = pr.resolve_profile("example-board", ext, shipped)
    assert (r.source, r.path, r.other_path) == ("shipped", ship_path, None)
    assert r.data == data


def test_only_extension(dirs):
    ext, shipped = dirs
    shipped.mkdir()
    ext_path, _ = put(ext)
    r = pr.resolve_profile("example-board", ext, shipped)
    assert (r.source, r.path, r.other_path) == ("extension", ext_path, None)


def test_extension_dir_none_uses_shipped(dirs):
    _, shipped = dirs
    put(shipped)
    r = pr.resolve_profile("example-board", None, shipped)
    assert r.source == "shipped"


def test_default_shipped_dir_is_package_profiles_dir():
    assert pr.SHIPPED_DIR.name == "profiles"
    assert pr.SHIPPED_DIR.parent.name == "avocado_flash_remote"


def test_neither_lists_names_from_both_dirs(dirs):
    ext, shipped = dirs
    put(ext, "board-a")
    put(shipped, "board-b")
    with pytest.raises(pr.UnknownBoard) as e:
        pr.resolve_profile("missing", ext, shipped)
    assert "board-a" in str(e.value) and "board-b" in str(e.value)
    assert e.value.known == ["board-a", "board-b"]


def test_list_known_sorted_deduped(dirs):
    ext, shipped = dirs
    put(ext, "zeta")
    put(ext, "alpha")
    put(shipped, "alpha")
    (shipped / "NotValid.json").write_text("{}")
    (shipped / "readme.txt").write_text("x")
    assert pr.list_known(ext, shipped) == ["alpha", "zeta"]


def test_list_known_missing_dirs(tmp_path):
    assert pr.list_known(tmp_path / "no", tmp_path / "nope") == []


def test_describe_names_both_when_both_exist(dirs):
    ext, shipped = dirs
    ext_path, _ = put(ext)
    ship_path, _ = put(shipped)
    text = pr.describe(pr.resolve_profile("example-board", ext, shipped))
    assert str(ext_path) in text and str(ship_path) in text
    assert "extension" in text and "shadows shipped" in text


def test_describe_shipped_only(dirs):
    _, shipped = dirs
    ship_path, _ = put(shipped)
    text = pr.describe(pr.resolve_profile("example-board", None, shipped))
    assert text == f"profile: example-board (shipped: {ship_path})"


def test_describe_extension_only(dirs):
    ext, shipped = dirs
    ext_path, _ = put(ext)
    shipped.mkdir()
    text = pr.describe(pr.resolve_profile("example-board", ext, shipped))
    assert text == f"profile: example-board (extension: {ext_path})"


@pytest.mark.parametrize("bad", ["../x", "a/b", "", "-x", "UPPER", "a b", "x\n", ".."])
def test_invalid_board_rejected_before_filesystem(bad):
    with pytest.raises(pr.InvalidBoard):
        pr.resolve_profile(bad, Exploding(), Exploding())


def test_hash_matches_profile_hash(dirs):
    _, shipped = dirs
    _, data = put(shipped)
    r = pr.resolve_profile("example-board", None, shipped)
    assert r.sha256 == profile_hash(data)
    assert r.profile == load_profile_bytes(data)


def test_whitespace_different_files_hash_differently(tmp_path):
    _, a = put(tmp_path / "a", indent=None)
    _, b = put(tmp_path / "b", indent=2)
    ra = pr.resolve_profile("example-board", None, tmp_path / "a")
    rb = pr.resolve_profile("example-board", None, tmp_path / "b")
    assert ra.profile == rb.profile
    assert ra.sha256 != rb.sha256


def test_invalid_extension_profile_does_not_fall_back(dirs):
    ext, shipped = dirs
    doc = base()
    doc["bogus"] = 1
    put(ext, doc=doc)
    put(shipped)
    with pytest.raises(ProfileError):
        pr.resolve_profile("example-board", ext, shipped)


def test_board_field_must_match_requested_name(dirs):
    _, shipped = dirs
    put(shipped, "wanted", doc=base("other-board"))
    with pytest.raises(ProfileError):
        pr.resolve_profile("wanted", None, shipped)


def test_symlink_inside_dir_ok(dirs):
    ext, _ = dirs
    real, _ = put(ext, name="real")
    (ext / "example-board.json").symlink_to("real.json")
    r = pr.resolve_profile("example-board", ext, None)
    assert r.real_path == real.resolve()


def test_symlink_escaping_dir_refused(dirs, tmp_path):
    ext, _ = dirs
    outside, _ = put(tmp_path / "outside")
    ext.mkdir()
    (ext / "example-board.json").symlink_to(outside)
    with pytest.raises(pr.UnsafeProfilePath):
        pr.resolve_profile("example-board", ext, None)


def test_dangling_symlink_refused(dirs):
    ext, _ = dirs
    ext.mkdir()
    (ext / "example-board.json").symlink_to(ext / "nowhere.json")
    with pytest.raises(pr.UnsafeProfilePath):
        pr.resolve_profile("example-board", ext, None)


def test_recheck_unchanged_passes(dirs):
    _, shipped = dirs
    put(shipped)
    pr.resolve_profile("example-board", None, shipped).recheck()


def test_recheck_detects_edit(dirs):
    _, shipped = dirs
    path, data = put(shipped)
    r = pr.resolve_profile("example-board", None, shipped)
    path.write_bytes(data + b"\n")
    with pytest.raises(pr.ProfileChanged):
        r.recheck()


def test_recheck_detects_replaced_inode_same_bytes(dirs):
    _, shipped = dirs
    path, data = put(shipped)
    r = pr.resolve_profile("example-board", None, shipped)
    tmp = shipped / "tmp.new"
    tmp.write_bytes(data)
    os.replace(tmp, path)
    with pytest.raises(pr.ProfileChanged):
        r.recheck()


def test_recheck_detects_retargeted_symlink(dirs):
    ext, _ = dirs
    _, data = put(ext, name="one")
    (ext / "two.json").write_bytes(data)
    link = ext / "example-board.json"
    link.symlink_to("one.json")
    r = pr.resolve_profile("example-board", ext, None)
    link.unlink()
    link.symlink_to("two.json")
    with pytest.raises(pr.ProfileChanged):
        r.recheck()


def test_recheck_detects_removed_file(dirs):
    _, shipped = dirs
    path, _ = put(shipped)
    r = pr.resolve_profile("example-board", None, shipped)
    path.unlink()
    with pytest.raises(pr.ProfileChanged):
        r.recheck()


def test_extension_can_pin_a_serial_over_the_shipped_generic_profile(tmp_path):
    import pathlib

    shipped_dir = pr.SHIPPED_DIR
    doc = json.loads((shipped_dir / "jetson-agx-orin-j5012.json").read_text())
    doc["target"]["identity"] = {"kind": "serial", "value": "0x0badc0de", "sysfs_attr": "serial"}
    ext = tmp_path / "ext"
    ext.mkdir()
    (ext / "jetson-agx-orin-j5012.json").write_text(json.dumps(doc))
    got = pr.resolve_profile("jetson-agx-orin-j5012", ext)
    assert got.source == "extension"
    assert (got.profile.target.identity.kind, got.profile.target.identity.value) == ("serial", "0x0badc0de")
    assert got.other_path == shipped_dir / "jetson-agx-orin-j5012.json"
    plain = pr.resolve_profile("jetson-agx-orin-j5012", None)
    assert plain.profile.target.identity.kind == "sysfs-name"
