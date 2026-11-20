#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0

"""avocado-cve-report waits for the merge without rebuilding the distro.

rm_work's do_rm_work_all depends on do_rm_work of every recipe its task graph
reaches, and each do_rm_work runs after everything its recipe builds. Through
the dependency on avocado-distro:do_multikernel_merge that is all of
avocado-distro: a report run on a CVE scan rebuilt the images and rewrote the
rootfs image's package while do_rpm_manifest read deploy/rpm.

  python3 -m unittest discover -s meta-avocado-sbom/tests -p 'test_*.py'
"""

import os
import re
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
RECIPE = os.path.join(HERE, "..", "recipes-avocado", "avocado-cve-report",
                      "avocado-cve-report.bb")


def statements():
    """Top-level lines, continuations joined and comments dropped."""
    with open(RECIPE) as f:
        text = f.read().replace("\\\n", " ")
    return [line.strip() for line in text.splitlines()
            if line.strip() and not line.lstrip().startswith("#")]


class ReportRecipeTasks(unittest.TestCase):
    def test_the_merge_dependency_names_the_merge(self):
        merge = [s for s in statements()
                 if re.match(r"AVOCADO_CVE_REPORT_MERGE\s*=", s)]
        self.assertEqual(len(merge), 1)
        self.assertIn("avocado-distro:do_multikernel_merge", merge[0])

    def test_both_readers_of_the_merged_evidence_wait_for_it(self):
        for task in ("do_rpm_manifest", "do_kernel_cve_improve"):
            with self.subTest(task=task):
                self.assertIn('%s[depends] += "${AVOCADO_CVE_REPORT_MERGE}"' % task,
                              statements())

    def test_rm_work_cannot_follow_the_merge_into_the_distro(self):
        self.assertIn("deltask do_rm_work_all", statements())


if __name__ == "__main__":
    unittest.main()
