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


def manifest_rcm_ids(stone_dir: pathlib.Path) -> dict[str, list[str]]:
    """Machine -> the manifest's storage_devices.rootdisk.tegraflash.rcm_ids."""
    out = {}
    for path in stone_dir.glob("*.json"):
        if SCRIPT not in path.read_text():
            continue
        data = json.loads(path.read_text())
        tf = data.get("storage_devices", {}).get("rootdisk", {}).get("tegraflash", {})
        out["avocado-" + path.stem.removeprefix("stone-")] = list(tf.get("rcm_ids", []))
    return out


def registry_rcm_ids() -> dict[str, str | None]:
    return {b.machine: b.rcm_id for b in all_boards() if b.family == "tegra"}


def rcm_mismatches(manifest: dict[str, list[str]], registry: dict[str, str | None]) -> list[str]:
    """Name each machine whose registry rcm_id is not exactly the manifest's one id.

    A manifest with ids and a registry entry with none (or the reverse) is also drift.
    """
    bad = []
    for machine in sorted(set(manifest) | set(registry)):
        ids = manifest.get(machine, [])
        have = registry.get(machine)
        if ids != ([] if have is None else [have]):
            bad.append(f"{machine}: manifest {ids} vs registry {have!r}")
    return bad


def test_registry_rcm_ids_match_manifests():
    manifest = manifest_rcm_ids(STONE_DIR)
    assert manifest["avocado-jetson-orin-nano"] == ["0955:7523"]
    assert rcm_mismatches(manifest, registry_rcm_ids()) == []


def test_rcm_id_drift_is_detected(tmp_path):
    for p in STONE_DIR.glob("*.json"):
        (tmp_path / p.name).write_text(p.read_text())
    nano = tmp_path / "stone-jetson-orin-nano.json"
    nano.write_text(nano.read_text().replace("0955:7523", "0955:7000"))
    bad = rcm_mismatches(manifest_rcm_ids(tmp_path), registry_rcm_ids())
    assert len(bad) == 1 and bad[0].startswith("avocado-jetson-orin-nano")


def test_registry_id_without_manifest_id_is_detected():
    registry = registry_rcm_ids()
    registry["avocado-icam-540"] = "0955:7523"
    bad = rcm_mismatches(manifest_rcm_ids(STONE_DIR), registry)
    assert len(bad) == 1 and bad[0].startswith("avocado-icam-540")
