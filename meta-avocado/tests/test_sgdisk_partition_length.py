# SPDX-License-Identifier: Apache-2.0
"""No disk-image script passes sgdisk a partition length one sector short.

sgdisk reads "-n <part>:<start>:+N" as a length of N sectors, not an end
offset, so "+$((size - 1))" makes every partition one sector short. That is
harmless for an image smaller than its partition, and fatal for var: its
btrfs is sized to the exact partition and then reports "device total_bytes
should be at most ...". Only a provision on the board shows it.

Run with:
    python3 -m unittest discover -s meta-avocado/tests
"""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

SHORT_LENGTH = re.compile(r'"-n"\s+"[^"]*:\+\$\(\([^)]*-\s*1\s*\)\)"')


class SgdiskPartitionLength(unittest.TestCase):
    def test_partition_length_is_not_one_short(self):
        scripts = sorted(ROOT.glob("meta-avocado*/stone/**/*.sh"))
        self.assertTrue(scripts)
        for path in scripts:
            for n, line in enumerate(path.read_text().splitlines(), 1):
                with self.subTest(f"{path.relative_to(ROOT)}:{n}"):
                    self.assertIsNone(
                        SHORT_LENGTH.search(line),
                        'sgdisk "+N" is a length: "+$((size - 1))" is one sector short')


if __name__ == "__main__":
    unittest.main()
