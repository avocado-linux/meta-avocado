"""Tests for the fixture trees the parity harness stages for the legacy script."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from parity import fixtures, stubs

STONE_DIR = Path(__file__).resolve().parents[3]
MANIFESTS = sorted(
    p
    for p in STONE_DIR.glob("stone-*.json")
    if "stone-provision-tegraflash.sh" in p.read_text()
)
DIR_KEYS = ("tegraflash_bsp", "tegraflash_tools", "tegraflash_carrier_bsp")


def _ids(paths):
    return [p.stem for p in paths]


def _string_entries(manifest_path):
    images = json.loads(Path(manifest_path).read_text())["storage_devices"]["rootdisk"]["images"]
    return {k: v for k, v in images.items() if isinstance(v, str)}


CARRIER_MANIFESTS = [p for p in MANIFESTS if "tegraflash_carrier_bsp" in _string_entries(p)]


def _stage_in(tmp_path, manifest, **kw):
    tmp_path.mkdir(parents=True, exist_ok=True)
    return _stage(tmp_path, manifest, **kw)


def _stage(tmp_path, manifest, **kw):
    stub_dir = tmp_path / "stubs"
    stubs.write_stubs(stub_dir, tmp_path / "log", tmp_path / "scenario.json")
    return fixtures.build_tree(manifest, tmp_path / "root", stub_dir, **kw)


def test_scan_finds_all_seven_manifests():
    assert len(MANIFESTS) == 7
    assert CARRIER_MANIFESTS


@pytest.mark.parametrize("manifest", MANIFESTS, ids=_ids(MANIFESTS))
def test_every_manifest_entry_exists(tmp_path, manifest):
    tree = _stage(tmp_path, manifest)
    entries = _string_entries(manifest)
    assert entries
    for key, name in entries.items():
        path = tree.data_dir / name
        if key in DIR_KEYS:
            assert path.is_dir(), key
        else:
            assert path.is_file(), key
    assert tree.manifest == tree.data_dir / "manifest.json"
    assert json.loads(tree.manifest.read_text()) == json.loads(manifest.read_text())
    assert tree.build_dir.is_dir()


@pytest.mark.parametrize("manifest", MANIFESTS, ids=_ids(MANIFESTS))
def test_placeholders_occur_exactly_once(tmp_path, manifest):
    tree = _stage(tmp_path, manifest)
    bsp = tree.data_dir / _string_entries(manifest)["tegraflash_bsp"]
    text = (bsp / "external-flash.xml.in").read_text()
    assert len(re.findall(r"APPUUID_b", text)) == 1
    assert len(re.findall(r"APPUUID(?!_b)", text)) == 1


@pytest.mark.parametrize("manifest", MANIFESTS, ids=_ids(MANIFESTS))
def test_bsp_holds_what_the_script_reads(tmp_path, manifest):
    tree = _stage(tmp_path, manifest)
    bsp = tree.data_dir / _string_entries(manifest)["tegraflash_bsp"]
    env = (bsp / ".env.initrd-flash").read_text()
    for key in ("BOOTDEV", "ROOTFS_DEVICE", "EXTERNAL_ROOTFS_DRIVE", "TOSIMGFILENAME"):
        assert re.search(rf"^{key}=", env, re.M), key
    flashvars = (bsp / "flashvars").read_text()
    assert re.search(r"^ODMDATA=", flashvars, re.M)
    assert (bsp / "internal-flash-emmc.xml").is_file()
    assert (bsp / "L4TConfiguration.dtbo").is_file()
    assert (bsp / "mkbootimg").is_file()
    # the stub is copied in so ./initrd-flash is intercepted
    assert (bsp / "initrd-flash").read_bytes() == (tree.stub_dir / "initrd-flash").read_bytes()
    assert (bsp / "initrd-flash").stat().st_mode & 0o100


@pytest.mark.parametrize("manifest", MANIFESTS, ids=_ids(MANIFESTS))
def test_overlays_named_by_manifest_exist_in_bsp(tmp_path, manifest):
    tree = _stage(tmp_path, manifest)
    tf = json.loads(manifest.read_text())["storage_devices"]["rootdisk"].get("tegraflash", {})
    bsp = tree.data_dir / _string_entries(manifest)["tegraflash_bsp"]
    for name in tf.get("overlays", []) + tf.get("dce_overlays", []):
        assert (bsp / name).is_file(), name


@pytest.mark.parametrize("manifest", CARRIER_MANIFESTS, ids=_ids(CARRIER_MANIFESTS))
def test_carrier_default_holds_only_placeholder(tmp_path, manifest):
    tree = _stage(tmp_path, manifest)
    carrier = tree.data_dir / _string_entries(manifest)["tegraflash_carrier_bsp"]
    assert [p.name for p in carrier.iterdir()] == [".placeholder"]
    assert tree.kernel_image is None


@pytest.mark.parametrize("manifest", CARRIER_MANIFESTS, ids=_ids(CARRIER_MANIFESTS))
def test_carrier_content_and_kernel(tmp_path, manifest):
    tree = _stage(tmp_path, manifest, carrier="CARRIER_LABEL=Acme\n", kernel=True)
    carrier = tree.data_dir / _string_entries(manifest)["tegraflash_carrier_bsp"]
    assert (carrier / "carrier.env").read_text() == "CARRIER_LABEL=Acme\n"
    assert any(p.name not in (".placeholder", "carrier.env") for p in carrier.iterdir())
    assert tree.kernel_image is not None and tree.kernel_image.is_file()
    initramfs = tree.data_dir / _string_entries(manifest)["initramfs"]
    assert initramfs.is_file()


def test_carrier_dict_renders_lines(tmp_path):
    tree = _stage(tmp_path, CARRIER_MANIFESTS[0], carrier={"CARRIER_LABEL": "x", "CARRIER_FV_A": "b"})
    carrier = tree.data_dir / _string_entries(CARRIER_MANIFESTS[0])["tegraflash_carrier_bsp"]
    assert (carrier / "carrier.env").read_text() == "CARRIER_LABEL=x\nCARRIER_FV_A=b\n"


@pytest.mark.parametrize("manifest", MANIFESTS, ids=_ids(MANIFESTS))
def test_drop_omits_entries(tmp_path, manifest):
    entries = _string_entries(manifest)
    tree = _stage(
        tmp_path,
        manifest,
        drop=("rootfs", "external-flash.xml.in")
        + (("tegraflash_carrier_bsp",) if "tegraflash_carrier_bsp" in entries else ()),
    )
    if "tegraflash_carrier_bsp" in entries:
        assert not (tree.data_dir / entries["tegraflash_carrier_bsp"]).exists()
    assert not (tree.data_dir / entries["rootfs"]).exists()
    assert (tree.data_dir / entries["var"]).is_file()
    bsp = tree.data_dir / entries["tegraflash_bsp"]
    assert not (bsp / "external-flash.xml.in").exists()
    assert (bsp / "flashvars").is_file()


def test_drop_bsp_directory(tmp_path):
    entries = _string_entries(MANIFESTS[0])
    tree = _stage(tmp_path, MANIFESTS[0], drop=("tegraflash_bsp",))
    assert not (tree.data_dir / entries["tegraflash_bsp"]).exists()


@pytest.mark.parametrize("token,count", [("appuuid", 0), ("appuuid_b", 0)])
def test_drop_placeholder_counts(tmp_path, token, count):
    tree = _stage(tmp_path, MANIFESTS[0], drop=(token,))
    bsp = tree.data_dir / _string_entries(MANIFESTS[0])["tegraflash_bsp"]
    text = (bsp / "external-flash.xml.in").read_text()
    if token == "appuuid":
        assert len(re.findall(r"APPUUID(?!_b)", text)) == count
        assert len(re.findall(r"APPUUID_b", text)) == 1
    else:
        assert len(re.findall(r"APPUUID_b", text)) == count
        assert len(re.findall(r"APPUUID(?!_b)", text)) == 1


def test_special_character_names_created_verbatim(tmp_path):
    """A manifest copy mutated before staging still yields every entry verbatim."""
    mutated = tmp_path / "mutated.json"
    data = json.loads(MANIFESTS[0].read_text())
    data["storage_devices"]["rootdisk"]["images"]["rootfs"] = "a;touch PWNED"
    mutated.write_text(json.dumps(data))
    tree = _stage(tmp_path, mutated)
    assert (tree.data_dir / "a;touch PWNED").is_file()
    assert not (tmp_path / "PWNED").exists()
    assert json.loads(tree.manifest.read_text())["storage_devices"]["rootdisk"]["images"]["rootfs"] == "a;touch PWNED"


def test_unknown_drop_name_raises_and_names_itself(tmp_path):
    with pytest.raises(ValueError, match="no-such-thing"):
        _stage(tmp_path, MANIFESTS[0], drop=("rootfs", "no-such-thing"))


def test_all_unmatched_names_are_listed(tmp_path):
    with pytest.raises(ValueError) as exc:
        _stage(tmp_path, MANIFESTS[0], drop=("typo-a", "typo-b", "var"))
    assert "typo-a" in str(exc.value) and "typo-b" in str(exc.value)
    assert "'var'" not in str(exc.value)


@pytest.mark.parametrize("manifest", MANIFESTS, ids=_ids(MANIFESTS))
def test_each_recognised_drop_kind_does_not_raise(tmp_path, manifest):
    entries = _string_entries(manifest)
    names = [
        "rootfs",  # image key
        entries["var"],  # image file name
        "external-flash.xml.in",  # BSP file name, external layout
        "internal-flash-emmc.xml",  # BSP file name, internal eMMC layout
        "L4TConfiguration.dtbo",
        "initrd-flash",
        ".env.initrd-flash",
        "flashvars",
        "mkbootimg",
    ]
    if "tegraflash_carrier_bsp" in entries:
        names.append("tegraflash_carrier_bsp")
    for i, name in enumerate(names):
        _stage_in(tmp_path / str(i), manifest, drop=(name,))
    _stage_in(tmp_path / "a", manifest, drop=("appuuid",))
    _stage_in(tmp_path / "b", manifest, drop=("appuuid_b",))


def test_bsp_name_with_bsp_dropped_raises(tmp_path):
    with pytest.raises(ValueError, match="flashvars"):
        _stage(tmp_path, MANIFESTS[0], drop=("tegraflash_bsp", "flashvars"))


def _partition_sizes(layout_text):
    return {
        m.group(1): int(m.group(2))
        for m in re.finditer(r'<partition name="([^"]+)">\s*<size>(\d+)</size>', layout_text)
    }


@pytest.mark.parametrize("manifest", MANIFESTS, ids=_ids(MANIFESTS))
def test_layouts_carry_numeric_app_and_esp_sizes_that_fit_the_images(tmp_path, manifest):
    tree = _stage(tmp_path, manifest)
    entries = _string_entries(manifest)
    bsp = tree.data_dir / entries["tegraflash_bsp"]
    for layout_name in ("external-flash.xml.in", "internal-flash-emmc.xml"):
        sizes = _partition_sizes((bsp / layout_name).read_text())
        assert "APP" in sizes and "esp" in sizes, layout_name
        assert (tree.data_dir / entries["rootfs"]).stat().st_size <= sizes["APP"]
        assert (tree.data_dir / entries["tegraflash_esp"]).stat().st_size <= sizes["esp"]
