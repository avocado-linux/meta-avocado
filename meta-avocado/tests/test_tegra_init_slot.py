# SPDX-License-Identifier: Apache-2.0
"""The Jetson initrd mounts the rootfs of the boot chain the firmware booted.

avocado-tegra-init reads the slot from the BootChainOsCurrent EFI variable.
The initramfs ships no awk, so a parse that calls it fails inside $(...)
without a word, the initrd always mounts APP, and every A/B update boots the
new slot's kernel on the old rootfs and is rolled back. This runs the script's
own slot-detection block with only the tools the initramfs has on PATH.

Run with:
    python3 -m unittest discover -s meta-avocado/tests
"""

import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

SCRIPT = (Path(__file__).resolve().parents[2] / "meta-avocado-nvidia" / "recipes-core"
          / "avocado-tegra-init" / "files" / "avocado-tegra-init")
EFIVAR = "/sys/firmware/efi/efivars/BootChainOsCurrent-781e084c-a330-417c-b678-38e696380cb9"
# What the slot block may call beyond sh builtins; awk is deliberately absent.
INITRAMFS_TOOLS = ("hexdump", "cut")


def _slot_block():
    m = re.search(r'^if \[ "\$foundslotsfx" != "yes" \]; then\n.*?^fi\n', SCRIPT.read_text(), re.M | re.S)
    assert m, "slot detection block not found"
    return m.group(0)


class TegraInitSlot(unittest.TestCase):
    def slot(self, attributes, value):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            (d / "bin").mkdir()
            for tool in INITRAMFS_TOOLS:
                (d / "bin" / tool).symlink_to(shutil.which(tool))
            var = d / "BootChainOsCurrent"
            var.write_bytes(attributes.to_bytes(4, "little") + value.to_bytes(4, "little"))
            body = 'slotsfx=""\nfoundslotsfx="no"\n' + _slot_block().replace(EFIVAR, str(var)) + 'printf %s "$slotsfx"\n'
            out = subprocess.run([shutil.which("sh"), "-c", body], env={"PATH": str(d / "bin")},
                                 capture_output=True, text=True, check=True)
            return out.stdout

    def test_slot_b_mounts_app_b(self):
        self.assertEqual(self.slot(6, 1), "_b")

    def test_non_volatile_attribute_is_accepted(self):
        self.assertEqual(self.slot(7, 1), "_b")

    def test_slot_a_mounts_app(self):
        self.assertEqual(self.slot(6, 0), "")


if __name__ == "__main__":
    unittest.main()
