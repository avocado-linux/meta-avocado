"""Every Jetson manifest that runs the tegraflash script names the engine directory."""

import json
from pathlib import Path

import pytest

STONE_DIR = Path(__file__).resolve().parents[2]
SCRIPT = "stone-provision-tegraflash.sh"
KEY = "tegraflash_engine"
# Literal on purpose: it is the DEPLOYDIR name the engine recipe installs, and the
# recipe is not read here so this test stays independent of it.
ENGINE_DIR = "tegraflash-engine"
EXPECTED_MANIFESTS = 7


def scan_manifests() -> list[Path]:
    return sorted(
        p for p in STONE_DIR.glob("stone-*.json") if SCRIPT in p.read_text()
    )


def check_manifest(path: Path) -> None:
    """Raise AssertionError naming the manifest when the engine entry is wrong."""
    data = json.loads(path.read_text())
    images = data["storage_devices"]["rootdisk"]["images"]
    assert images.get(KEY) == ENGINE_DIR, (
        f"{path.name}: storage_devices.rootdisk.images.{KEY} must be "
        f"{ENGINE_DIR!r}, got {images.get(KEY)!r}"
    )


def test_seven_manifests_name_the_script():
    assert len(scan_manifests()) == EXPECTED_MANIFESTS


@pytest.mark.parametrize("manifest", scan_manifests(), ids=lambda p: p.name)
def test_manifest_names_engine_directory(manifest):
    check_manifest(manifest)


@pytest.mark.parametrize("manifest", scan_manifests(), ids=lambda p: p.name)
def test_engine_key_only_under_rootdisk_images(manifest):
    data = json.loads(manifest.read_text())
    found = []

    def walk(node, trail):
        if isinstance(node, dict):
            for k, v in node.items():
                if k == KEY:
                    found.append(".".join(trail))
                walk(v, trail + [k])

    walk(data, [])
    assert found == ["storage_devices.rootdisk.images"], manifest.name


def test_engine_value_identical_in_all_manifests():
    values = {
        json.loads(p.read_text())["storage_devices"]["rootdisk"]["images"].get(KEY)
        for p in scan_manifests()
    }
    assert values == {ENGINE_DIR}


def test_mutated_copy_missing_entry_fails_naming_manifest(tmp_path):
    src = scan_manifests()[0]
    data = json.loads(src.read_text())
    del data["storage_devices"]["rootdisk"]["images"][KEY]
    copy = tmp_path / src.name
    copy.write_text(json.dumps(data))
    with pytest.raises(AssertionError) as exc:
        check_manifest(copy)
    assert src.name in str(exc.value)


def test_mutated_copy_with_wrong_value_fails(tmp_path):
    src = scan_manifests()[0]
    text = src.read_text()
    old = f'"{KEY}": "{ENGINE_DIR}"'
    assert text.count(old) == 1
    copy = tmp_path / src.name
    copy.write_text(text.replace(old, f'"{KEY}": "other"'))
    with pytest.raises(AssertionError):
        check_manifest(copy)
