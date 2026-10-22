# SPDX-License-Identifier: Apache-2.0
"""A Jetson rollback verifies the failed boot before it switches slots.

After a boot-chain switch the firmware keeps a BootChainFwStatus variable until
`nvbootctrl verify` deletes it, and it ignores a later slot switch while the
variable is set. The rollback runs before the extensions merge, so the merge's
own `nvbootctrl verify` never runs in a failed boot and the board comes back on
the failed slot. The rollback action therefore has to run verify itself first.

Run with:
    PYTHONPATH=meta-avocado/lib python3 -m unittest discover -s meta-avocado/tests
"""

import json
import unittest
from pathlib import Path

STONE_DIR = Path(__file__).resolve().parents[2] / "meta-avocado-nvidia" / "stone"
SWITCH = ["nvbootctrl", "set-active-boot-slot", "{previous_slot}"]
VERIFY = ["nvbootctrl", "verify"]


def _commands(actions):
    return [a["command"] for a in actions if a.get("type") == "command"]


def _jetson_manifests():
    """Every stone manifest whose activate action switches slots with nvbootctrl."""
    found = {}
    for path in sorted(STONE_DIR.glob("stone-*.json")):
        update = json.loads(path.read_text()).get("update") or {}
        if any(c[:2] == ["nvbootctrl", "set-active-boot-slot"] for c in _commands(update.get("activate", []))):
            found[path.name] = update
    return found


class JetsonRollback(unittest.TestCase):
    def test_manifests_with_nvbootctrl_activation_are_found(self):
        # Guards the discovery below: an empty set would make every other test pass vacuously.
        self.assertGreaterEqual(len(_jetson_manifests()), 5)

    def test_rollback_verifies_the_failed_boot_before_switching_slot(self):
        for name, update in _jetson_manifests().items():
            with self.subTest(manifest=name):
                self.assertEqual(_commands(update["rollback"]), [VERIFY, SWITCH])

    def test_activation_still_switches_slot_without_verifying(self):
        # Verifying on activation would mark the new, unproven boot as good before it booted.
        for name, update in _jetson_manifests().items():
            with self.subTest(manifest=name):
                activate = _commands(update["activate"])
                self.assertIn(["nvbootctrl", "set-active-boot-slot", "{inactive_slot}"], activate)
                self.assertNotIn(VERIFY, activate)


if __name__ == "__main__":
    unittest.main()
