# SPDX-License-Identifier: Apache-2.0
"""An OS update carries everything a flash writes, or the gap is tracked.

A board is only as maintainable as its update path: a kernel, device tree or
bootloader that changes only on a reflash cannot be fixed in the field. Each
stone manifest is checked against what its own flash writes:

- partitioned layouts: every image a partition is written from, except
  device state (var, the U-Boot environment);
- vendor-flash layouts (the flash layout lives in vendor tooling, not in the
  manifest): the components listed in VENDOR_COMPONENTS.

A component an update does not carry must be listed in ota_coverage_gaps.json
with the reason. The list may only shrink: an entry whose component is now
covered fails too, so the list stays the true to-do list.

Run with:
    python3 -m unittest discover -s meta-avocado/tests
"""

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GAPS = json.loads((Path(__file__).with_name("ota_coverage_gaps.json")).read_text())

# Device state, written once at provision and kept across updates.
STATE_IMAGES = {"var", "uboot_env"}

# What a flash writes on boards whose layout is not in the manifest.
VENDOR_COMPONENTS = {
    "meta-avocado-nvidia": {"rootfs", "boot", "kernel_dtb", "bootloader"},
    "meta-avocado-qcom": {"rootfs", "uki", "bootloader"},
}


def _manifests():
    return sorted(ROOT.glob("meta-avocado*/stone/stone-*.json"))


def _required(path, manifest):
    if path.parts[-3] in VENDOR_COMPONENTS:
        return set(VENDOR_COMPONENTS[path.parts[-3]])
    images = {p.get("image") for dev in (manifest.get("storage_devices") or {}).values()
              for p in dev.get("partitions") or []}
    return {i for i in images if i} - STATE_IMAGES


def _covered(manifest):
    artifacts = ((manifest.get("update") or {}).get("os_artifacts") or {}).values()
    # One image per slot (uki_a, uki_b) is still the one component.
    return {a["image_key"].removesuffix("_a").removesuffix("_b") for a in artifacts}


class OtaCoverage(unittest.TestCase):
    def test_manifests_are_found(self):
        self.assertGreater(len(_manifests()), 20)

    def test_every_flashed_component_is_updated_or_tracked(self):
        for path in _manifests():
            manifest = json.loads(path.read_text())
            with self.subTest(path.name):
                untracked = _required(path, manifest) - _covered(manifest) - set(GAPS.get(path.stem, {}))
                self.assertFalse(untracked, f"{path.stem}: an update never writes {sorted(untracked)}; "
                                 "add it to update.os_artifacts, or to ota_coverage_gaps.json with the reason")

    def test_tracked_gaps_are_still_gaps(self):
        manifests = {p.stem: p for p in _manifests()}
        for stem, gaps in GAPS.items():
            with self.subTest(stem):
                self.assertIn(stem, manifests, f"{stem}: no such manifest; drop its gap entry")
                path = manifests[stem]
                manifest = json.loads(path.read_text())
                closed = set(gaps) & _covered(manifest)
                stale = set(gaps) - _required(path, manifest)
                self.assertFalse(closed | stale, f"{stem}: {sorted(closed | stale)} no longer a gap; "
                                 "remove it from ota_coverage_gaps.json")
                for component, reason in gaps.items():
                    self.assertTrue(reason.strip(), f"{stem}/{component}: a gap needs its reason")


if __name__ == "__main__":
    unittest.main()
