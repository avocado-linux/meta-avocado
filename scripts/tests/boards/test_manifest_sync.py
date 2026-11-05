"""The registry and the Jetson stone manifests must name the same machines."""

import json
import pathlib

from avocado_flash_boards import all_boards

STONE_DIR = pathlib.Path(__file__).resolve().parents[3] / "meta-avocado-nvidia" / "stone"
SCRIPT = "stone-provision-tegraflash.sh"


def manifest_machines(stone_dir: pathlib.Path) -> set[str]:
    """Machines whose manifest names the tegraflash provision script."""
    out = set()
    for path in stone_dir.glob("*.json"):
        if SCRIPT in path.read_text():
            json.loads(path.read_text())
            out.add("avocado-" + path.stem.removeprefix("stone-"))
    return out


def registry_machines(family: str = "tegra") -> set[str]:
    return {b.machine for b in all_boards() if b.family == family}


def diff(manifests: set[str], registry: set[str]) -> tuple[set[str], set[str]]:
    return manifests - registry, registry - manifests


def drift_message(manifests: set[str], registry: set[str]) -> str:
    """Name the offending files and machines so a failure says what to fix."""
    missing, extra = diff(manifests, registry)
    files = sorted("stone-" + m.removeprefix("avocado-") + ".json" for m in missing)
    return (
        f"manifests with no registry entry (add a board or remove the file): {files}; "
        f"registry machines with no manifest (orphaned entries): {sorted(extra)}"
    )


def test_every_jetson_manifest_has_an_entry_and_back():
    manifests = manifest_machines(STONE_DIR)
    registry = registry_machines()
    assert diff(manifests, registry) == (set(), set()), drift_message(manifests, registry)
    assert manifests, "no stone manifest names the provision script"


def test_manifest_without_entry_is_detected(tmp_path):
    for p in STONE_DIR.glob("*.json"):
        (tmp_path / p.name).write_text(p.read_text())
    (tmp_path / "stone-jetson-new.json").write_text(f'{{"script": "{SCRIPT}"}}')
    manifests, registry = manifest_machines(tmp_path), registry_machines()
    missing, extra = diff(manifests, registry)
    assert missing == {"avocado-jetson-new"}
    assert extra == set()
    message = drift_message(manifests, registry)
    assert "stone-jetson-new.json" in message
    assert "orphaned entries): []" in message


def test_entry_without_manifest_is_detected(tmp_path):
    for p in STONE_DIR.glob("*.json"):
        if p.name != "stone-icam-540.json":
            (tmp_path / p.name).write_text(p.read_text())
    manifests, registry = manifest_machines(tmp_path), registry_machines()
    missing, extra = diff(manifests, registry)
    assert missing == set()
    assert extra == {"avocado-icam-540"}
    message = drift_message(manifests, registry)
    assert "['avocado-icam-540']" in message
    assert "no registry entry (add a board or remove the file): []" in message
