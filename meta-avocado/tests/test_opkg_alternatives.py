#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0

"""Pin where nativesdk update-alternatives keeps its registry.

CI only parses the opkg-utils bbappend, so its sed expression and the
``grep -qxF`` guard behind it never run there. These tests apply the
bbappend's own sed expression to the line upstream ships and evaluate the
resulting ``ad``, once per kind of root:

  * with OPKG_OFFLINE_ROOT set (avocado-cli on a target sysroot), the registry
    stays at that root's /usr/lib, where the target's own update-alternatives
    reads it;
  * with it unset (a nativesdk scriptlet running in place), the registry moves
    into the SDK, so the host's /usr/lib is never touched.

  python3 -m unittest discover -s meta-avocado/tests -p 'test_*.py'
"""

import re
import subprocess
import unittest
from pathlib import Path

BBAPPEND = (
    Path(__file__).resolve().parents[1]
    / "recipes-devtools"
    / "opkg-utils"
    / "opkg-utils_%.bbappend"
)

# The line upstream's update-alternatives defines, which the bbappend patches.
UPSTREAM_LINE = 'ad="$OPKG_OFFLINE_ROOT/usr/lib/opkg/alternatives"'
# What bitbake expands ${nonarch_libdir} to inside the SDK.
SDK_LIBDIR = "/opt/sdk/usr/lib"


def _recipe_text():
    return BBAPPEND.read_text()


def _sed_expression():
    """The text of the first `-e '...'` sed script in the bbappend, with
    ${nonarch_libdir} expanded the way bitbake does before the shell runs."""
    match = re.search(r"-e '([^']*)'", _recipe_text())
    assert match, "no sed -e expression in the bbappend"
    return match.group(1).replace("${nonarch_libdir}", SDK_LIBDIR)


def _guard_line():
    """The line the recipe's `grep -qxF` requires in the patched script."""
    match = re.search(r"grep -qxF '([^']*)'", _recipe_text())
    assert match, "no grep -qxF guard in the bbappend"
    return match.group(1).replace("${nonarch_libdir}", SDK_LIBDIR)


def _patch(script):
    return subprocess.run(
        ["sed", "-e", _sed_expression()],
        input=script,
        capture_output=True,
        text=True,
        check=True,
    ).stdout


def _registry(script, offline_root):
    """Run `script` and return what it left in $ad."""
    env = {"PATH": "/usr/bin:/bin"}
    if offline_root is not None:
        env["OPKG_OFFLINE_ROOT"] = offline_root
    result = subprocess.run(
        ["sh", "-c", script + '\nprintf %s "$ad"'],
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout


class OpkgAlternativesRegistry(unittest.TestCase):
    def test_offline_root_keeps_the_root_libdir(self):
        patched = _patch(UPSTREAM_LINE + "\n")
        self.assertEqual(
            _registry(patched, "/tmp/rootfs"),
            "/tmp/rootfs/usr/lib/opkg/alternatives",
        )

    def test_no_offline_root_uses_the_sdk_libdir(self):
        patched = _patch(UPSTREAM_LINE + "\n")
        self.assertEqual(
            _registry(patched, None),
            SDK_LIBDIR + "/opkg/alternatives",
        )

    def test_unpatched_line_names_the_host_libdir(self):
        # Guards the two tests above: with no patch the unset case lands in
        # the host's /usr/lib, so they fail when the bbappend stops patching.
        self.assertEqual(
            _registry(UPSTREAM_LINE + "\n", None),
            "/usr/lib/opkg/alternatives",
        )

    def test_guard_line_is_present_after_patching(self):
        self.assertIn(_guard_line(), _patch(UPSTREAM_LINE + "\n").splitlines())

    def test_guard_line_is_absent_when_upstream_changes_the_line(self):
        # The recipe's grep -qxF fails the build in this case.
        changed = 'ad="$OPKG_OFFLINE_ROOT/usr/lib/opkg/other"\n'
        self.assertNotIn(_guard_line(), _patch(changed).splitlines())


if __name__ == "__main__":
    unittest.main()
