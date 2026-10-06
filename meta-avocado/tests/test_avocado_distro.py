# SPDX-License-Identifier: Apache-2.0
"""revision_tag names the source a local build came from.

Run with:
    PYTHONPATH=meta-avocado/lib python3 -m unittest discover -s meta-avocado/tests
"""

import os
import re
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

import avocado_distro

TAG = re.compile(r"^(\d+)\.g([0-9a-f]{8})(\.dirty)?$")
UNKNOWN = "0.gunknown"


def _git(cwd, *args):
    env = dict(os.environ, GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_SYSTEM=os.devnull)
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false", *args],
        cwd=cwd, env=env, check=True, capture_output=True,
    )


class Fixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="avocado-distro-test-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        patcher = mock.patch.dict(
            os.environ, {"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull}
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def repo(self, name="repo", commits=1):
        """A repo whose layer lives in a subdirectory, as meta-avocado does."""
        root = os.path.join(self.tmp, name)
        layer = os.path.join(root, "meta-avocado")
        os.makedirs(os.path.join(layer, "conf"))
        _git(root, "init", "-q")
        for i in range(commits):
            with open(os.path.join(layer, "conf", "layer.conf"), "w") as f:
                f.write("# revision %d\n" % i)
            _git(root, "add", "-A")
            _git(root, "commit", "-q", "-m", "commit %d" % i)
        return root, layer


class TestRevisionTag(Fixture):
    def test_clean_checkout_reports_commit_count_and_short_revision(self):
        _, layer = self.repo(commits=3)
        m = TAG.match(avocado_distro.revision_tag(layer))
        self.assertIsNotNone(m)
        self.assertEqual(m.group(1), "3")
        self.assertIsNone(m.group(3))

    def test_count_increases_with_each_commit(self):
        root, layer = self.repo(commits=1)
        first = avocado_distro.revision_tag(layer)
        with open(os.path.join(layer, "conf", "layer.conf"), "a") as f:
            f.write("# more\n")
        _git(root, "commit", "-q", "-a", "-m", "next")
        second = avocado_distro.revision_tag(layer)
        self.assertEqual(TAG.match(first).group(1), "1")
        self.assertEqual(TAG.match(second).group(1), "2")
        self.assertNotEqual(first, second)

    def test_edit_to_a_tracked_file_marks_the_tree_dirty(self):
        _, layer = self.repo()
        with open(os.path.join(layer, "conf", "layer.conf"), "a") as f:
            f.write("# edited\n")
        self.assertTrue(avocado_distro.revision_tag(layer).endswith(".dirty"))

    def test_staged_change_marks_the_tree_dirty(self):
        root, layer = self.repo()
        with open(os.path.join(layer, "conf", "layer.conf"), "a") as f:
            f.write("# staged\n")
        _git(root, "add", "-A")
        self.assertTrue(avocado_distro.revision_tag(layer).endswith(".dirty"))

    def test_new_untracked_file_marks_the_tree_dirty(self):
        _, layer = self.repo()
        with open(os.path.join(layer, "new.bb"), "w") as f:
            f.write("x\n")
        self.assertTrue(avocado_distro.revision_tag(layer).endswith(".dirty"))

    def test_ignored_file_does_not_mark_the_tree_dirty(self):
        root, layer = self.repo()
        with open(os.path.join(root, ".gitignore"), "w") as f:
            f.write("scratch\n")
        _git(root, "add", "-A")
        _git(root, "commit", "-q", "-m", "ignore")
        with open(os.path.join(layer, "scratch"), "w") as f:
            f.write("x\n")
        self.assertFalse(avocado_distro.revision_tag(layer).endswith(".dirty"))

    def test_directory_that_is_not_a_checkout_reads_unknown(self):
        layer = os.path.join(self.tmp, "tarball", "meta-avocado")
        os.makedirs(os.path.join(layer, "conf"))
        with open(os.path.join(layer, "conf", "layer.conf"), "w") as f:
            f.write("x\n")
        self.assertEqual(avocado_distro.revision_tag(layer), UNKNOWN)

    def test_layer_extracted_inside_another_repo_reads_unknown(self):
        outer, _ = self.repo(name="outer")
        layer = os.path.join(outer, "vendored", "meta-avocado")
        os.makedirs(os.path.join(layer, "conf"))
        with open(os.path.join(layer, "conf", "layer.conf"), "w") as f:
            f.write("x\n")
        self.assertEqual(avocado_distro.revision_tag(layer), UNKNOWN)

    def test_missing_path_reads_unknown(self):
        self.assertEqual(avocado_distro.revision_tag(os.path.join(self.tmp, "absent")), UNKNOWN)

    def test_empty_path_reads_unknown(self):
        self.assertEqual(avocado_distro.revision_tag(""), UNKNOWN)
        self.assertEqual(avocado_distro.revision_tag(None), UNKNOWN)

    def test_missing_git_binary_reads_unknown(self):
        _, layer = self.repo()
        with mock.patch.dict(os.environ, {"PATH": ""}):
            self.assertEqual(avocado_distro.revision_tag(layer), UNKNOWN)

    def test_shallow_clone_reads_unknown_count_but_keeps_the_revision(self):
        src, _ = self.repo(name="src", commits=3)
        clone = os.path.join(self.tmp, "clone")
        _git(self.tmp, "clone", "-q", "--depth", "1", "file://" + src, clone)
        m = TAG.match(avocado_distro.revision_tag(os.path.join(clone, "meta-avocado")))
        self.assertIsNotNone(m)
        self.assertEqual(m.group(1), "0")


def vercmp(a, b):
    """rpmvercmp for the strings used here: digit runs compare as numbers and
    beat letters, letter runs compare as text, and the longer string wins a tie.

    Written out rather than asking `rpm`, which the CI image may not ship and a
    skipped test would hide.
    """
    ta, tb = re.findall(r"\d+|[A-Za-z]+", a), re.findall(r"\d+|[A-Za-z]+", b)
    for x, y in zip(ta, tb):
        if x.isdigit() != y.isdigit():
            return 1 if x.isdigit() else -1
        if x.isdigit():
            x, y = int(x), int(y)
        if x != y:
            return 1 if x > y else -1
    return (len(ta) > len(tb)) - (len(ta) < len(tb))


class TestOrdering(unittest.TestCase):
    def test_hash_alone_does_not_order_builds(self):
        self.assertEqual(vercmp("2026.0+gf0000000", "2026.0+g10000000"), 1)

    def test_later_commit_sorts_above_earlier_whatever_the_hash(self):
        older = "2026.0+9.gf0000000"
        newer = "2026.0+10.g10000000"
        self.assertEqual(vercmp(newer, older), 1)

    def test_local_build_sorts_below_any_published_build_id(self):
        self.assertEqual(vercmp("2026.0+4000.gabcdef01", "2026.1"), -1)

    @unittest.skipUnless(shutil.which("rpm"), "rpm not installed")
    def test_helper_agrees_with_rpm(self):
        for a, b in [
            ("2026.0+gf0000000", "2026.0+g10000000"),
            ("2026.0+10.g10000000", "2026.0+9.gf0000000"),
            ("2026.0+4000.gabcdef01", "2026.1"),
        ]:
            out = subprocess.run(
                ["rpm", "--eval", "%%{lua: print(rpm.vercmp('%s','%s'))}" % (a, b)],
                capture_output=True, text=True, check=True,
            ).stdout.strip()
            self.assertEqual(int(out), vercmp(a, b), (a, b))


if __name__ == "__main__":
    unittest.main()
