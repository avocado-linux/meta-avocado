"""Tests for the closed, versioned board profile loader."""

import copy
import json

import pytest

from avocado_flash_remote import profile
from avocado_flash_remote.profile import ProfileError, load_profile_bytes, profile_hash

DEVICE_SECTORS = 122314752
EFI = "C12A7328-F81F-11D2-BA4B-00A0C93EC93B"
LINUX = "0FC63DAF-8483-4772-8E79-3D69D8477DE4"


def base():
    return {
        "schema_version": 1,
        "board": "example-board",
        "description": "an example",
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
                "params": {"label": "Avocado", "loader_path": "\\EFI\\BOOT\\BOOTX64.EFI"}},
        "guard": {"strategy": "boot-arg",
                  "params": {"argument": "avocado.flash=1", "partitions": ["boot"]}},
        "staging": {"dir": "/var/tmp/avocado-flash", "min_free_kib": 1048576},
        "state_dir": "/var/lib/avocado-flash",
    }


def dump(d):
    return json.dumps(d).encode()


def mutated(fn):
    d = copy.deepcopy(base())
    fn(d)
    return dump(d)


def test_valid_profile_loads():
    p = load_profile_bytes(dump(base()))
    assert p.board == "example-board"
    assert p.target.sectors == DEVICE_SECTORS
    assert p.target.identity.kind == "by-path"
    assert p.layout.strategy == "explicit-table"
    assert p.images["boot"].partition == 1
    assert p.checks == ("device-identity", "device-empty")
    assert p.staging.min_free_kib == 1048576
    assert p.state_dir == "/var/lib/avocado-flash"


def test_profile_is_immutable():
    p = load_profile_bytes(dump(base()))
    with pytest.raises(Exception):
        p.board = "other"


def test_unknown_top_level_key():
    with pytest.raises(ProfileError, match="extra"):
        load_profile_bytes(mutated(lambda d: d.update(extra=1)))


def test_unknown_nested_key():
    with pytest.raises(ProfileError, match=r"target\.bogus"):
        load_profile_bytes(mutated(lambda d: d["target"].update(bogus=1)))


def test_unknown_image_key():
    with pytest.raises(ProfileError, match=r"images\.boot\.bogus"):
        load_profile_bytes(mutated(lambda d: d["images"]["boot"].update(bogus=1)))


@pytest.mark.parametrize(
    "path",
    [
        ("board",),
        ("target",),
        ("target", "device"),
        ("target", "sectors"),
        ("target", "identity", "value"),
        ("layout", "strategy"),
        ("images", "boot", "max_bytes"),
        ("checks",),
        ("arm",),
        ("guard", "strategy"),
        ("staging", "dir"),
        ("staging", "min_free_kib"),
        ("state_dir",),
    ],
)
def test_missing_required_field(path):
    def drop(d):
        node = d
        for k in path[:-1]:
            node = node[k]
        del node[path[-1]]

    with pytest.raises(ProfileError, match=path[-1]):
        load_profile_bytes(mutated(drop))


@pytest.mark.parametrize("ver", [0, 2, "1", True])
def test_bad_schema_version(ver):
    with pytest.raises(ProfileError, match="schema_version"):
        load_profile_bytes(mutated(lambda d: d.update(schema_version=ver)))


def test_float_schema_version():
    raw = dump(base()).replace(b'"schema_version": 1', b'"schema_version": 1.0')
    with pytest.raises(ProfileError, match="non-canonical"):
        load_profile_bytes(raw)


def test_missing_identity():
    with pytest.raises(ProfileError, match="identity"):
        load_profile_bytes(mutated(lambda d: d["target"].pop("identity")))


def test_empty_identity_value():
    with pytest.raises(ProfileError, match="identity"):
        load_profile_bytes(
            mutated(lambda d: d["target"]["identity"].update(value=""))
        )


def test_empty_identity_object():
    with pytest.raises(ProfileError, match="identity"):
        load_profile_bytes(mutated(lambda d: d["target"].update(identity={})))


def test_invalid_identity_kind():
    with pytest.raises(ProfileError, match="kind"):
        load_profile_bytes(
            mutated(lambda d: d["target"]["identity"].update(kind="vibes"))
        )


def test_identity_sysfs_attr_optional_string():
    d = base()
    d["target"]["identity"] = {"kind": "sysfs-name", "value": "x", "sysfs_attr": "name"}
    assert load_profile_bytes(dump(d)).target.identity.sysfs_attr == "name"


def test_duplicate_key_top_level():
    raw = dump(base())[:-1] + b', "board": "other"}'
    with pytest.raises(ProfileError, match="duplicate"):
        load_profile_bytes(raw)


def test_duplicate_key_nested():
    raw = dump(base()).replace(
        b'"require_empty": false', b'"require_empty": false, "require_empty": true'
    )
    with pytest.raises(ProfileError, match="duplicate"):
        load_profile_bytes(raw)


def test_float_sectors():
    raw = dump(base()).replace(str(DEVICE_SECTORS).encode(), b"122314752.0", 1)
    with pytest.raises(ProfileError):
        load_profile_bytes(raw)


def test_bool_for_sectors():
    with pytest.raises(ProfileError, match="sectors"):
        load_profile_bytes(mutated(lambda d: d["target"].update(sectors=True)))


def test_nan_rejected():
    raw = dump(base()).replace(b'"min_free_kib": 1048576', b'"min_free_kib": NaN')
    with pytest.raises(ProfileError, match="non-canonical"):
        load_profile_bytes(raw)


def test_infinity_rejected():
    raw = dump(base()).replace(b'"min_free_kib": 1048576', b'"min_free_kib": Infinity')
    with pytest.raises(ProfileError, match="non-canonical"):
        load_profile_bytes(raw)


def test_invalid_json_and_non_object():
    with pytest.raises(ProfileError):
        load_profile_bytes(b"{not json")
    with pytest.raises(ProfileError):
        load_profile_bytes(b"[]")
    with pytest.raises(ProfileError):
        load_profile_bytes(b"\xff\xfe")


def test_unknown_arm_strategy():
    with pytest.raises(ProfileError, match="teleport"):
        load_profile_bytes(
            mutated(lambda d: d["arm"].update(strategy="teleport"))
        )


def test_bad_guard_params():
    with pytest.raises(ProfileError, match="guard"):
        load_profile_bytes(
            mutated(lambda d: d["guard"]["params"].update(partitions="boot"))
        )


def test_image_partition_not_in_table():
    with pytest.raises(ProfileError, match=r"images\.boot\.partition"):
        load_profile_bytes(
            mutated(lambda d: d["images"]["boot"].update(partition=9))
        )


def test_guard_partition_not_in_table():
    with pytest.raises(ProfileError, match=r"guard"):
        load_profile_bytes(
            mutated(lambda d: d["guard"]["params"].update(partitions=["nope"]))
        )


def test_sectors_must_match_device_sectors():
    with pytest.raises(ProfileError, match="sectors"):
        load_profile_bytes(mutated(lambda d: d["target"].update(sectors=DEVICE_SECTORS + 1)))


@pytest.mark.parametrize("name", ["a/b.img", "-rf", "../x", ""])
def test_bad_image_file_name(name):
    with pytest.raises(ProfileError, match=r"images\.boot\.file"):
        load_profile_bytes(mutated(lambda d: d["images"]["boot"].update(file=name)))


@pytest.mark.parametrize("bad", ["/dev/shm/x", "/sys/x", "/proc/x", "/dev"])
def test_staging_dir_forbidden(bad):
    with pytest.raises(ProfileError, match=r"staging\.dir"):
        load_profile_bytes(mutated(lambda d: d["staging"].update(dir=bad)))


def test_checks_duplicates():
    with pytest.raises(ProfileError, match="checks"):
        load_profile_bytes(
            mutated(lambda d: d.update(checks=["device-empty", "device-empty"]))
        )


def test_relative_state_dir():
    with pytest.raises(ProfileError, match="state_dir"):
        load_profile_bytes(mutated(lambda d: d.update(state_dir="var/lib/x")))


def test_bad_board_name():
    with pytest.raises(ProfileError, match="board"):
        load_profile_bytes(mutated(lambda d: d.update(board="Bad Board")))


def test_hash_is_of_exact_bytes():
    raw = dump(base())
    spaced = json.dumps(base(), indent=2).encode()
    assert profile_hash(raw) == profile_hash(bytes(raw))
    assert profile_hash(raw) != profile_hash(spaced)
    assert len(profile_hash(raw)) == 64
    assert load_profile_bytes(raw).board == load_profile_bytes(spaced).board


def test_module_is_stdlib_only():
    import ast
    import pathlib

    tree = ast.parse(pathlib.Path(profile.__file__).read_text())
    allowed = {"__future__", "dataclasses", "hashlib", "json", "re", "typing",
               "avocado_flash_remote", "copy", "types"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            assert all(a.name.split(".")[0] in allowed for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            assert (node.module or "").split(".")[0] in allowed or node.level


# ---- 5.33: trust-boundary validation ----


@pytest.mark.parametrize("board", ["-foo", "foo\n", "Foo", "foo_bar", "", "foo bar"])
def test_board_name_pattern_is_strict(board):
    with pytest.raises(ProfileError, match="board"):
        load_profile_bytes(mutated(lambda d: d.update(board=board)))


def test_loader_and_resolver_share_one_board_pattern():
    from avocado_flash_remote import profile as profile_mod
    from avocado_flash_remote import profile_resolve

    assert profile_resolve._BOARD_RE is profile_mod._BOARD_RE
    with pytest.raises(profile_resolve.InvalidBoard):
        profile_resolve._check_board("-foo")


def test_two_image_roles_may_not_target_the_same_partition():
    def m(d):
        d["images"]["root"]["partition"] = 1

    with pytest.raises(ProfileError, match="boot.*root|root.*boot"):
        load_profile_bytes(mutated(m))


@pytest.mark.parametrize("key", ["state_dir"])
@pytest.mark.parametrize("value", ["/", "//", "/."])
def test_state_dir_may_not_be_the_filesystem_root(key, value):
    with pytest.raises(ProfileError, match=key):
        load_profile_bytes(mutated(lambda d: d.update({key: value})))


@pytest.mark.parametrize("value", ["/", "//", "/."])
def test_staging_dir_may_not_be_the_filesystem_root(value):
    with pytest.raises(ProfileError, match="staging.dir"):
        load_profile_bytes(mutated(lambda d: d["staging"].update(dir=value)))


@pytest.mark.parametrize("first", [0, 33])
def test_first_lba_below_the_gpt_header_is_refused(first):
    def m(d):
        d["layout"]["params"]["first_lba"] = first

    with pytest.raises(ProfileError, match="first_lba"):
        load_profile_bytes(mutated(m))
