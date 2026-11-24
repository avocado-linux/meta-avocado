# SPDX-License-Identifier: Apache-2.0
"""linux-raspberrypi 6.6: conmakehash keeps the build path out of its output.

conmakehash writes its input's absolute path into consolemap_deftbl.c, which
the -src package ships with kernel debug sources. Upstream dropped the path
in v6.11, so only the 6.6 kernel takes the backport. Checks the patch is
wired to the 6.6 recipe alone and that its printf keeps one argument per
conversion.

Run with:
    PYTHONPATH=meta-avocado/lib python3 -m unittest discover -s meta-avocado/tests
"""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LINUX = ROOT / "meta-avocado-raspberrypi" / "recipes-kernel" / "linux"
BBAPPEND = LINUX / "linux-raspberrypi_6.6.bbappend"
PATCH_NAME = "0001-tty-vt-conmakehash-remove-non-portable-code-printing.patch"
PATCH = LINUX / "linux-raspberrypi-6.6" / PATCH_NAME


def _bbappend_matches(bbappend, recipe):
    # bitbake: "%" in a bbappend name matches any remaining version string.
    stem, pattern = Path(recipe).stem, Path(bbappend).stem
    if "%" in pattern:
        return stem.startswith(pattern.split("%", 1)[0])
    return stem == pattern


def _diff_lines():
    """The hunk header and body, without a format-patch signature."""
    lines = PATCH.read_text().split("\n@@ ", 1)[1].splitlines()
    return lines[:lines.index("-- ")] if "-- " in lines else lines


def _hunk(sign):
    """Lines of the patch's diff body on one side: '-' old, '+' new."""
    lines = []
    for line in _diff_lines()[1:]:
        if line.startswith("@@") or not line:
            continue
        if line[0] in (" ", sign):
            lines.append(line[1:])
    return "\n".join(lines)


def _header_printf(source):
    """The header printf's conversions and arguments."""
    m = re.search(r'printf\("(.*?)",\s*([^;]*)\);', source, re.S)
    assert m, "the header printf is gone"
    conversions = [c for c in re.findall(r"%%|%[ds]", m.group(1)) if c != "%%"]
    args = [a.strip() for a in m.group(2).split(",") if a.strip()]
    return m.group(1), conversions, args


def _applied_patches(text):
    """file:// patches in active SRC_URI assignments that do_patch applies."""
    text = re.sub(r"(?m)^\s*#.*$", "", text)
    files = []
    # Unconditional additions only: an override would scope it to one machine.
    for m in re.finditer(r'(?m)^SRC_URI(?::append|:prepend)?\s*(?:\+=|=\+|\.=|=\.|\?=|=)\s*"([^"]*)"',
                         text):
        for entry in m.group(1).split():
            name, _, params = entry.partition(";")
            if not name.startswith("file://"):
                continue
            if re.search(r"(?:^|;)apply=(?:no|0|false)(?:;|$)", params):
                continue
            files.append(name[len("file://"):])
    return files


class ConmakehashBackport(unittest.TestCase):
    def test_only_the_6_6_recipe_takes_the_patch(self):
        self.assertTrue(_bbappend_matches(BBAPPEND, "linux-raspberrypi_6.6.bb"))
        self.assertFalse(_bbappend_matches(BBAPPEND, "linux-raspberrypi_6.12.bb"))
        self.assertIn(PATCH_NAME, _applied_patches(BBAPPEND.read_text()))
        self.assertNotRegex(BBAPPEND.read_text(), r"(?m)^SRC_URI:remove\b.*" + re.escape(PATCH_NAME))
        # The 6.12 kernel already carries the upstream fix; no other recipe
        # may pick the patch up.
        for path in ROOT.glob("meta-*/**/*.bb*"):
            if path == BBAPPEND:
                continue
            with self.subTest(file=str(path.relative_to(ROOT))):
                text = path.read_text(errors="replace")
                self.assertNotIn(PATCH_NAME, text)
                self.assertNotIn("linux-raspberrypi-6.6", text)

    def test_the_patch_is_on_the_bbappend_search_path(self):
        m = re.search(r'^FILESEXTRAPATHS:prepend := "\$\{THISDIR\}/([^:"]+):"$',
                      BBAPPEND.read_text(), re.M)
        self.assertIsNotNone(m)
        self.assertTrue((LINUX / m.group(1) / PATCH_NAME).is_file())

    def test_the_patch_targets_the_path_printing_header(self):
        old, new = _hunk("-"), _hunk("+")
        self.assertIn("conmakehash %s > [this file]", old)
        self.assertIn("argv[1]", old)
        self.assertNotIn("conmakehash %s", new)
        self.assertNotIn("argv[1]", new)
        self.assertIn("Automatically generated file; Do not edit.", new)

    def test_the_header_printf_keeps_one_argument_per_conversion(self):
        _, conversions, args = _header_printf(_hunk("-"))
        self.assertEqual((conversions, args), (["%s", "%d"], ["argv[1]", "fontlen"]))
        fmt, conversions, args = _header_printf(_hunk("+"))
        self.assertEqual((conversions, args), (["%d"], ["fontlen"]))
        self.assertIn("u8 dfont_unicount[%d] = ", fmt)

    def test_the_hunk_counts_match_its_body(self):
        # git am rejects a hunk whose header disagrees with its lines.
        lines = _diff_lines()
        m = re.match(r"-\d+,(\d+) \+\d+,(\d+) @@", lines[0])
        self.assertIsNotNone(m)
        body = [l for l in lines[1:] if l]
        self.assertTrue(all(l[0] in " -+" for l in body))
        self.assertEqual(sum(l[0] in " -" for l in body), int(m.group(1)))
        self.assertEqual(sum(l[0] in " +" for l in body), int(m.group(2)))

    def test_the_patch_is_marked_as_a_backport(self):
        text = PATCH.read_text()
        self.assertRegex(text, r"(?m)^Upstream-Status: Backport \[\S+7258fdd7d745\S*\]$")
        self.assertRegex(text, r"(?m)^Signed-off-by: ")


if __name__ == "__main__":
    unittest.main()
