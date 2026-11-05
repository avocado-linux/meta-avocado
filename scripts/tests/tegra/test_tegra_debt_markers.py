"""Every deliberate-debt marker in the tegra package names its ceiling and its upgrade trigger."""

import pathlib
import re

PKG = pathlib.Path(__file__).resolve().parents[2] / "avocado_flash_tegra"
MARKER = "devtool-debt:"


def markers_in(text, name="<text>"):
    """Yield (file, line number, text) for each marker's contiguous comment block."""
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if not line.lstrip().startswith("#") or MARKER not in line:
            continue
        block = [line.lstrip()[1:].strip()]
        for nxt in lines[i + 1 :]:
            if not nxt.lstrip().startswith("#") or MARKER in nxt:
                break
            block.append(nxt.lstrip()[1:].strip())
        yield name, i + 1, " ".join(block)


def markers(pkg=PKG):
    for path in sorted(pkg.glob("*.py")):
        yield from markers_in(path.read_text(), path.name)


def problems(found):
    bad = []
    for name, lineno, text in found:
        if not re.search(r"\bceiling:\s*\S", text, re.I):
            bad.append(f"{name}:{lineno} has no ceiling")
        if not re.search(r"\bupgrade trigger:\s*\S", text, re.I):
            bad.append(f"{name}:{lineno} has no upgrade trigger")
    return bad


def test_the_scan_reads_the_package_files():
    assert len(list(PKG.glob("*.py"))) > 1


def test_the_package_carries_no_marker():
    assert [f"{f}:{n}" for f, n, _ in markers()] == []


def test_the_scan_of_a_package_dir_reports_a_seeded_marker_without_a_trigger(tmp_path):
    (tmp_path / "m.py").write_text("# devtool-debt: a table.\n# Ceiling: one.\nX = {}\n")
    assert problems(markers(tmp_path)) == ["m.py:1 has no upgrade trigger"]


def test_every_marker_names_a_ceiling_and_an_upgrade_trigger():
    assert not problems(markers())


def test_a_marker_without_an_upgrade_trigger_is_reported():
    text = "# devtool-debt: a table.\n# Ceiling: one machine.\nX = {}\n"
    assert problems(markers_in(text, "m.py")) == ["m.py:1 has no upgrade trigger"]


def test_a_marker_without_a_ceiling_is_reported():
    text = "# devtool-debt: a table.\n# Upgrade trigger: a second machine.\nX = {}\n"
    assert problems(markers_in(text, "m.py")) == ["m.py:1 has no ceiling"]


def test_an_empty_trigger_is_reported():
    text = "# devtool-debt: a table.\n# Ceiling: one.\n# Upgrade trigger:\nX = {}\n"
    assert problems(markers_in(text, "m.py")) == ["m.py:1 has no upgrade trigger"]


def test_a_complete_marker_is_clean_and_counted_once():
    text = "# devtool-debt: a table.\n# Ceiling: one.\n# Upgrade trigger: two.\nX = {}\n"
    found = list(markers_in(text, "m.py"))
    assert len(found) == 1 and problems(found) == []
