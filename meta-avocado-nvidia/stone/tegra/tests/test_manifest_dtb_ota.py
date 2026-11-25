"""The AGX Orin manifest ships the kernel device tree as an OS update artifact.

The entry is read by stone's bundle builder, not by the provisioning engine, so
the engine must accept the manifest unchanged and stage nothing for the key.
"""

import copy
import json
import re
import subprocess
from pathlib import Path

from avocado_tegraflash.manifest import read_manifest, require_image_keys, staged_names

STONE_DIR = Path(__file__).resolve().parents[2]
MANIFEST = STONE_DIR / "stone-jetson-agx-orin.json"
LAYOUT_DIR = STONE_DIR.parent / "recipes-bsp" / "tegra-binaries" / "tegra-storage-layout"
OTA_IMAGE = "kernel-dtb-ota.dtb"
SLOTS = ["A_kernel-dtb", "B_kernel-dtb"]


def load() -> dict:
    return json.loads(MANIFEST.read_text())


def head_manifest() -> dict:
    out = subprocess.run(
        ["git", "show", f"HEAD:{MANIFEST.relative_to(_repo_root()).as_posix()}"],
        cwd=MANIFEST.parent,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return json.loads(out)


def _repo_root() -> Path:
    top = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        cwd=MANIFEST.parent,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    return Path(top)


def test_engine_reader_accepts_the_manifest_and_required_keys_hold():
    manifest = read_manifest(MANIFEST)
    require_image_keys(manifest)


def test_engine_stages_nothing_under_the_ota_image_name():
    names = staged_names(read_manifest(MANIFEST), tos_destination="tos.img")
    staged = {n for group in names.values() for n in group}
    assert OTA_IMAGE not in staged
    assert "kernel_" + OTA_IMAGE not in staged
    assert "kernel_dtb_ota" not in names


def test_images_names_the_fixed_ota_image():
    assert load()["storage_devices"]["rootdisk"]["images"]["kernel_dtb_ota"] == OTA_IMAGE


def test_os_artifact_dtb_points_at_that_image_and_the_slot_pair_in_order():
    dtb = load()["update"]["os_artifacts"]["dtb"]
    assert dtb == {"image_key": "kernel_dtb_ota", "slot_partitions": SLOTS}


def test_slot_partitions_exist_in_every_storage_layout():
    layouts = sorted(LAYOUT_DIR.glob("*.xml"))
    assert layouts, f"no storage layouts under {LAYOUT_DIR}"
    holders = []
    for xml in layouts:
        names = set(re.findall(r'<partition name="([^"]+)"', xml.read_text()))
        if set(SLOTS) <= names:
            holders.append(xml.name)
    assert holders, "no storage layout defines both kernel-dtb slot partitions"


def test_only_the_two_new_entries_differ_from_head():
    """images.dtb and every provisioning key stay exactly as they were."""
    expected = copy.deepcopy(head_manifest())
    expected["storage_devices"]["rootdisk"]["images"]["kernel_dtb_ota"] = OTA_IMAGE
    expected["update"]["os_artifacts"]["dtb"] = {
        "image_key": "kernel_dtb_ota",
        "slot_partitions": SLOTS,
    }
    assert load() == expected


def test_rootfs_and_boot_artifacts_are_unchanged():
    arts = load()["update"]["os_artifacts"]
    assert arts["rootfs"] == {"image_key": "rootfs", "slot_partitions": ["APP", "APP_b"]}
    assert arts["boot"] == {"image_key": "boot", "slot_partitions": ["A_kernel", "B_kernel"]}
