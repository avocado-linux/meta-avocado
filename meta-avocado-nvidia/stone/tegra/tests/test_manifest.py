"""read_manifest: absent or null values read as empty, as jq's `// empty` does."""

import dataclasses
import json

import pytest

from avocado_tegraflash import EngineError
from avocado_tegraflash.manifest import KEYS, Key, Manifest, read_manifest


def write(tmp_path, doc):
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(doc))
    return path


def rootdisk(images=None, tegraflash=None):
    doc = {"storage_devices": {"rootdisk": {}}}
    if images is not None:
        doc["storage_devices"]["rootdisk"]["images"] = images
    if tegraflash is not None:
        doc["storage_devices"]["rootdisk"]["tegraflash"] = tegraflash
    return doc


def test_images_values_are_read_by_name(tmp_path):
    m = read_manifest(write(tmp_path, rootdisk(images={"rootfs": "r.erofs", "var": "v.btrfs"})))
    assert (m.rootfs, m.var) == ("r.erofs", "v.btrfs")


def test_tegraflash_scalar_and_lists_are_read(tmp_path):
    doc = rootdisk(
        tegraflash={"sd_device": "mmcblk0", "overlays": ["a.dtbo", "b.dtbo"], "dce_overlays": ["c.dtbo"]}
    )
    m = read_manifest(write(tmp_path, doc))
    assert (m.sd_device, m.overlays, m.dce_overlays) == ("mmcblk0", ("a.dtbo", "b.dtbo"), ("c.dtbo",))


def test_empty_object_reads_every_value_as_empty(tmp_path):
    m = read_manifest(write(tmp_path, {}))
    assert m == Manifest()


def test_default_manifest_has_empty_strings_and_empty_lists():
    m = Manifest()
    assert (m.rootfs, m.dtb, m.sd_device, m.overlays, m.dce_overlays) == ("", "", "", (), ())


def test_null_values_read_as_empty(tmp_path):
    doc = rootdisk(images={"rootfs": None, "dtb": None}, tegraflash={"overlays": None, "sd_device": None})
    m = read_manifest(write(tmp_path, doc))
    assert (m.rootfs, m.dtb, m.overlays, m.sd_device) == ("", "", (), "")


def test_null_section_reads_as_empty(tmp_path):
    m = read_manifest(write(tmp_path, rootdisk(images=None, tegraflash=None) | {"x": 1}))
    assert m.rootfs == ""


def test_null_rootdisk_reads_as_empty(tmp_path):
    m = read_manifest(write(tmp_path, {"storage_devices": {"rootdisk": None}}))
    assert m == Manifest()


def test_empty_overlay_list_reads_as_empty_tuple(tmp_path):
    m = read_manifest(write(tmp_path, rootdisk(tegraflash={"overlays": []})))
    assert m.overlays == ()


def test_unicode_value_survives(tmp_path):
    m = read_manifest(write(tmp_path, rootdisk(images={"rootfs": "ré.erofs"})))
    assert m.rootfs == "ré.erofs"


def test_unrelated_keys_are_ignored(tmp_path):
    doc = rootdisk(images={"rootfs": "r", "boot": {"out": "boot.img"}})
    assert read_manifest(write(tmp_path, doc)).rootfs == "r"


def test_every_declared_key_is_a_manifest_field():
    assert {k.name for k in KEYS} <= {f.name for f in dataclasses.fields(Manifest)}


def test_every_declared_key_round_trips(tmp_path):
    images = {k.name: f"{k.name}.img" for k in KEYS if k.section == "images"}
    tegraflash = {k.name: f"{k.name}.val" for k in KEYS if k.section == "tegraflash" and k.name == "sd_device"}
    m = read_manifest(write(tmp_path, rootdisk(images=images, tegraflash=tegraflash)))
    assert all(getattr(m, name) == f"{name}.img" for name in images)


def test_keys_are_the_fourteen_oracle_reads_plus_one_engine_only_key():
    assert len(KEYS) == 15


def test_optional_keys_are_the_five_with_reasons():
    optional = {(k.section, k.name) for k in KEYS if k.optional}
    assert optional == {
        ("images", "dtb"),
        ("images", "bpmp_dtb"),
        ("tegraflash", "overlays"),
        ("tegraflash", "dce_overlays"),
        ("tegraflash", "rcm_ids"),
    }


def test_every_optional_key_carries_a_reason():
    assert all(k.reason for k in KEYS if k.optional)


def test_key_is_frozen():
    with pytest.raises(dataclasses.FrozenInstanceError):
        KEYS[0].name = "x"  # type: ignore[misc]


def test_manifest_is_frozen():
    with pytest.raises(dataclasses.FrozenInstanceError):
        Manifest().rootfs = "x"  # type: ignore[misc]


def test_key_fields_are_positional_in_declared_order():
    assert Key("images", "rootfs", False, "") == Key(section="images", name="rootfs", optional=False, reason="")


def test_absent_file_is_refused(tmp_path):
    with pytest.raises(EngineError, match="manifest"):
        read_manifest(tmp_path / "missing.json")


def test_malformed_json_is_refused(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text("{not json")
    with pytest.raises(EngineError, match="manifest"):
        read_manifest(path)


@pytest.mark.parametrize(
    "doc, key",
    [
        ([], "(top level)"),
        ("x", "(top level)"),
        ({"storage_devices": []}, "storage_devices"),
        ({"storage_devices": "x"}, "storage_devices"),
        ({"storage_devices": {"rootdisk": "x"}}, "storage_devices.rootdisk"),
        ({"storage_devices": {"rootdisk": ["a"]}}, "storage_devices.rootdisk"),
        (rootdisk(images="x"), "storage_devices.rootdisk.images"),
        (rootdisk(tegraflash=["x"]), "storage_devices.rootdisk.tegraflash"),
    ],
)
def test_a_non_object_where_an_object_is_required_is_refused_naming_the_path(tmp_path, doc, key):
    with pytest.raises(EngineError, match=key.replace("(", r"\(").replace(")", r"\)")):
        read_manifest(write(tmp_path, doc))


@pytest.mark.parametrize("name", ["overlays", "dce_overlays"])
@pytest.mark.parametrize("value", ["x.dtbo", {"a": "b"}, 5, True])
def test_a_non_list_overlays_value_is_refused_naming_the_key(tmp_path, name, value):
    with pytest.raises(EngineError, match=f"storage_devices.rootdisk.tegraflash.{name}"):
        read_manifest(write(tmp_path, rootdisk(tegraflash={name: value})))


@pytest.mark.parametrize("value", [{"a": "b"}, ["x"], True, False])
def test_a_container_or_boolean_where_a_string_is_required_is_refused(tmp_path, value):
    with pytest.raises(EngineError, match="storage_devices.rootdisk.images.rootfs"):
        read_manifest(write(tmp_path, rootdisk(images={"rootfs": value})))
    with pytest.raises(EngineError, match="storage_devices.rootdisk.tegraflash.sd_device"):
        read_manifest(write(tmp_path, rootdisk(tegraflash={"sd_device": value})))


@pytest.mark.parametrize("item", [["b"], True])
def test_a_container_or_boolean_inside_an_overlay_list_is_refused(tmp_path, item):
    with pytest.raises(EngineError, match="overlays"):
        read_manifest(write(tmp_path, rootdisk(tegraflash={"overlays": ["a.dtbo", item]})))


def test_absent_null_and_scalar_values_keep_their_defaults_and_str_conversion(tmp_path):
    doc = rootdisk(images={"rootfs": 7, "var": None}, tegraflash={"overlays": [1, "b.dtbo"]})
    m = read_manifest(write(tmp_path, doc))
    assert (m.rootfs, m.var, m.dtb, m.overlays, m.dce_overlays) == ("7", "", "", ("1", "b.dtbo"), ())
    assert read_manifest(write(tmp_path, {"storage_devices": None})) == Manifest()


def _mutant_reader(tmp_path, old, new):
    import importlib
    import shutil
    import sys
    from pathlib import Path

    import avocado_tegraflash

    pkg = Path(avocado_tegraflash.__file__).resolve().parent
    dest = tmp_path / "mut"
    shutil.copytree(pkg, dest / "avocado_tegraflash", ignore=shutil.ignore_patterns("__pycache__"))
    target = dest / "avocado_tegraflash" / "manifest.py"
    src = target.read_text()
    assert src.count(old) == 1
    target.write_text(src.replace(old, new))
    saved = {k: v for k, v in sys.modules.items() if k.startswith("avocado_tegraflash")}
    for k in saved:
        del sys.modules[k]
    sys.path.insert(0, str(dest))
    try:
        return importlib.import_module("avocado_tegraflash.manifest").read_manifest
    finally:
        sys.path.remove(str(dest))
        for k in [k for k in sys.modules if k.startswith("avocado_tegraflash")]:
            del sys.modules[k]
        sys.modules.update(saved)


@pytest.mark.parametrize(
    "old, doc",
    [
        ("if not isinstance(value, dict):", rootdisk(images="x")),
        ("if not isinstance(value, list):", rootdisk(tegraflash={"overlays": "x.dtbo"})),
        ("if isinstance(value, (dict, list, bool)):", rootdisk(images={"rootfs": {"a": 1}})),
        ("if isinstance(value, (dict, list, bool)):", rootdisk(images={"rootfs": True})),
    ],
)
def test_mutation_removing_a_type_check_lets_the_defective_manifest_through(tmp_path, old, doc):
    read = _mutant_reader(tmp_path, old, "if False:")
    path = write(tmp_path, doc)
    try:
        read(path)
    except Exception as exc:
        assert type(exc).__name__ != "EngineError", "mutant still refused"


def test_rcm_ids_default_to_empty_and_absent_key_is_accepted(tmp_path):
    assert Manifest().rcm_ids == ()
    assert read_manifest(write(tmp_path, rootdisk(tegraflash={"sd_device": "x"}))).rcm_ids == ()


def test_rcm_ids_are_read_as_a_tuple(tmp_path):
    doc = rootdisk(tegraflash={"rcm_ids": ["0955:7523", "0955:7c18"]})
    assert read_manifest(write(tmp_path, doc)).rcm_ids == ("0955:7523", "0955:7c18")


@pytest.mark.parametrize("bad", ["0955:75ZZ", "0955:7C18", "955:7523", "0955-7523", "0955:75233", "", " 0955:7523"])
def test_a_malformed_rcm_id_is_refused_naming_the_key(tmp_path, bad):
    with pytest.raises(EngineError, match=r"tegraflash\.rcm_ids"):
        read_manifest(write(tmp_path, rootdisk(tegraflash={"rcm_ids": [bad]})))


@pytest.mark.parametrize("value", ["0955:7523", {"a": 1}, 5, True])
def test_a_non_list_rcm_ids_is_refused_naming_the_key(tmp_path, value):
    with pytest.raises(EngineError, match=r"tegraflash\.rcm_ids.*list"):
        read_manifest(write(tmp_path, rootdisk(tegraflash={"rcm_ids": value})))


LITERAL_REQUIRED = ("rootfs", "var", "initramfs", "tegraflash_initramfs", "tegraflash_esp", "tegraflash_tos")


def test_the_required_image_set_is_exactly_these_six():
    from avocado_tegraflash.manifest import REQUIRED_IMAGES

    assert REQUIRED_IMAGES == LITERAL_REQUIRED


def test_require_image_keys_names_every_missing_key():
    from avocado_tegraflash.manifest import require_image_keys

    with pytest.raises(EngineError) as exc:
        require_image_keys(Manifest(rootfs="a.img", var="b.img"))
    for key in LITERAL_REQUIRED[2:]:
        assert f"images.{key}" in str(exc.value)
    assert "images.rootfs" not in str(exc.value)
    require_image_keys(Manifest(**{k: f"{k}.img" for k in LITERAL_REQUIRED}))


@pytest.mark.parametrize("key", LITERAL_REQUIRED)
def test_each_required_key_absent_is_refused_including_tegraflash_tos(key):
    from avocado_tegraflash.manifest import require_image_keys

    values = {k: "x.img" for k in LITERAL_REQUIRED}
    del values[key]
    with pytest.raises(EngineError, match=rf"images\.{key}"):
        require_image_keys(Manifest(**values))


@pytest.mark.parametrize("key", ["rootfs", "var", "tegraflash_esp", "dtb"])
@pytest.mark.parametrize("value", ["x/", "x/.", "x/..", ".", "..", "/"])
def test_an_image_value_with_no_file_name_is_refused_naming_the_key(tmp_path, key, value):
    with pytest.raises(EngineError, match=rf"images\.{key}.*file name"):
        read_manifest(write(tmp_path, rootdisk(images={key: value})))


def test_an_image_value_with_a_directory_part_and_a_file_name_is_accepted(tmp_path):
    assert read_manifest(write(tmp_path, rootdisk(images={"rootfs": "a/b/r.img"}))).rootfs == "a/b/r.img"


def _named(**overrides):
    from avocado_tegraflash.manifest import require_image_keys

    values = {k: f"{k}.img" for k in LITERAL_REQUIRED}
    values.update(overrides)
    require_image_keys(Manifest(**values))


def test_rootfs_and_esp_in_different_directories_with_the_same_name_are_refused_naming_both_keys():
    with pytest.raises(EngineError) as exc:
        _named(rootfs="r/esp.img", tegraflash_esp="e/esp.img")
    msg = str(exc.value)
    assert "rootfs" in msg and "tegraflash_esp" in msg and "esp.img" in msg


def test_two_required_images_with_the_same_basename_are_refused():
    with pytest.raises(EngineError, match=r"var.*initramfs|initramfs.*var"):
        _named(var="a/data.img", initramfs="b/data.img")


@pytest.mark.parametrize(
    "key,value",
    [
        ("rootfs", "esp.img"),
        ("var", "x/initrd-flash.img"),
        ("initramfs", "esp.img"),
        ("dtb", "initrd-flash.img"),
    ],
)
def test_an_image_whose_staged_name_is_another_images_fixed_destination_is_refused(key, value):
    with pytest.raises(EngineError, match="stage"):
        _named(**{key: value})


def test_a_dtb_collides_with_its_own_kernel_prefixed_copy_of_another_image():
    with pytest.raises(EngineError, match="kernel_a.dtb"):
        _named(dtb="a.dtb", bpmp_dtb="kernel_a.dtb")


def test_the_esp_image_may_itself_be_named_esp_img():
    _named(tegraflash_esp="x/esp.img")


def test_the_flash_initramfs_may_itself_be_named_initrd_flash_img():
    _named(tegraflash_initramfs="initrd-flash.img")
