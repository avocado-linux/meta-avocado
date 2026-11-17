# SPDX-License-Identifier: Apache-2.0
"""otelcol keeps the klauspost/cpuid/v2 module that only amd64 builds import.

zeebo/xxh3 imports cpuid from its amd64 sources only, so update_modules run
from a non-x86 build drops it from otelcol-go-mods.inc and its licence from
otelcol-licenses.inc. x86-64 builds then fail in do_compile trying to download
the module (#618, fixed again after #531/#535). The licence entry must stay
x86-64 only: Go extracts the module, and its LICENSE, only there.

Run with:
    PYTHONPATH=meta-avocado/lib python3 -m unittest discover -s meta-avocado/tests
"""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OTELCOL = ROOT / "meta-avocado-shared" / "recipes-devtools" / "otelcol"
MODULE = "github.com/klauspost/cpuid/v2"


def _go_sum_version():
    versions = set(re.findall(rf"^{re.escape(MODULE)} (v\S+?)(?:/go\.mod)? h1:", (OTELCOL / "otelcol" / "go.sum").read_text(), re.M))
    assert len(versions) == 1, versions
    return versions.pop()


def _x86_64_licences():
    m = re.search(r'^LIC_FILES_CHKSUM:append:x86-64\s*=\s*"([^"]*)"', (OTELCOL / "otelcol-licenses.inc").read_text(), re.M)
    return m.group(1) if m else ""


class OtelcolCpuid(unittest.TestCase):
    def test_go_sum_carries_cpuid(self):
        self.assertTrue(_go_sum_version().startswith("v2."))

    def test_go_mods_fetch_cpuid(self):
        self.assertIn(f"gomod://{MODULE};version={_go_sum_version()};",
                      (OTELCOL / "otelcol-go-mods.inc").read_text())

    def test_cpuid_licence_checked_on_x86_64_only(self):
        entry = f"file://pkg/mod/{MODULE}@{_go_sum_version()}/LICENSE;"
        self.assertIn(entry, _x86_64_licences())
        self.assertEqual((OTELCOL / "otelcol-licenses.inc").read_text().count(entry), 1)


if __name__ == "__main__":
    unittest.main()
