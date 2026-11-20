# SPDX-License-Identifier: Apache-2.0
"""nvidia.ko and nvidia-modeset.ko carry no build host or build time.

nvdisplay's utils.mk writes an id string into both modules from `$(WHOAMI)`,
$(HOSTNAME) and `$(DATE)`, run when the module builds. The bbappend pins all
three on the make command line. The stub below has utils.mk's shape - `?=` for
two, `ifndef` for HOSTNAME, the commands run in backticks - and sits two
recursive makes below the command line, as utils.mk does under meta-tegra's
top Makefile.

Run with:
    PYTHONPATH=meta-avocado/lib python3 -m unittest discover -s meta-avocado/tests
"""

import os
import re
import shutil
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BBAPPEND = (ROOT / "meta-avocado-nvidia" / "recipes-kernel" / "nvidia-kernel-oot"
            / "nvidia-kernel-oot_%.bbappend")

STUB = textwrap.dedent("""\
    WHOAMI ?= whoami
    ifndef HOSTNAME
      HOSTNAME = $(shell hostname)
    endif
    DATE ?= date
    all:
    \t@echo "(`$(WHOAMI)`@$(HOSTNAME))  `$(DATE)`"
    """)
CHAIN = "all:\n\t@$(MAKE) --no-print-directory -f {next}\n"


def _extra_oemake():
    found = re.findall(r"^EXTRA_OEMAKE \+= '(.*\bWHOAMI=.*)'$", BBAPPEND.read_text(), re.M)
    assert len(found) == 1, found
    return found[0]


def _gnu_date():
    try:
        out = subprocess.run(["date", "-u", "-d", "@0", "+%Y"], capture_output=True, text=True)
    except OSError:
        return False
    return out.returncode == 0 and out.stdout.strip() == "1970"


@unittest.skipUnless(shutil.which("make") and _gnu_date(), "needs make and GNU date")
class NvidiaIdString(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="nvidia-oot-repro-test-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        for name, text in (("outer.mk", CHAIN.format(next="middle.mk")),
                           ("middle.mk", CHAIN.format(next="utils.mk")),
                           ("utils.mk", STUB)):
            Path(self.tmp, name).write_text(text)

    def stamp(self, sde, host):
        # bitbake expands ${SOURCE_DATE_EPOCH}; oe_runmake hands the rest to
        # the shell, which takes the quotes.
        extra = _extra_oemake().replace("${SOURCE_DATE_EPOCH}", str(sde))
        env = dict(os.environ, HOSTNAME=host, USER=host, LOGNAME=host)
        return subprocess.run(["sh", "-c", "make -s -f outer.mk " + extra], cwd=self.tmp,
                              env=env, capture_output=True, text=True, check=True).stdout

    def test_the_stamp_names_no_build_host(self):
        self.assertEqual(self.stamp(1771545600, "pod-a").split("  ")[0], "(oe-user@oe-host)")

    def test_the_stamp_is_the_source_date_epoch(self):
        for sde, date in ((1771545600, "Fri Feb 20 00:00:00 UTC 2026"),
                          (1771632000, "Sat Feb 21 00:00:00 UTC 2026")):
            with self.subTest(sde=sde):
                self.assertEqual(self.stamp(sde, "pod-a").split("  ")[1].strip(), date)

    def test_two_hosts_build_the_same_stamp(self):
        self.assertEqual(self.stamp(1771545600, "pod-a"), self.stamp(1771545600, "pod-b"))


if __name__ == "__main__":
    unittest.main()
