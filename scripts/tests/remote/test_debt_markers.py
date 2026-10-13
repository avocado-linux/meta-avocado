"""Every deliberate-debt marker in the package names its ceiling and its upgrade trigger."""

import pathlib
import re

PKG = pathlib.Path(__file__).resolve().parents[2] / "avocado_flash_remote"
MARKER = "devtool-debt:"
EXPECTED_MARKERS = 9


def markers():
    """Yield (file, line number, text) for each marker's contiguous comment block."""
    for path in sorted(PKG.glob("*.py")):
        lines = path.read_text().splitlines()
        for i, line in enumerate(lines):
            if not line.lstrip().startswith("#") or MARKER not in line:
                continue
            block = [line.lstrip()[1:].strip()]
            for nxt in lines[i + 1 :]:
                if not nxt.lstrip().startswith("#") or MARKER in nxt:
                    break
                block.append(nxt.lstrip()[1:].strip())
            yield path.name, i + 1, " ".join(block)


def test_markers_exist():
    found = list(markers())
    assert len(found) == EXPECTED_MARKERS, [f"{f}:{n}" for f, n, _ in found]


def test_every_marker_names_a_ceiling_and_an_upgrade_trigger():
    bad = []
    for name, lineno, text in markers():
        if not re.search(r"\bceiling:\s*\S", text, re.I):
            bad.append(f"{name}:{lineno} has no ceiling")
        if not re.search(r"\bupgrade trigger:\s*\S", text, re.I):
            bad.append(f"{name}:{lineno} has no upgrade trigger")
    assert not bad, bad


def test_the_status_build_match_exemption_is_marked_where_it_is_made():
    lines = (PKG / "cli.py").read_text().splitlines()
    at = next(i for i, l in enumerate(lines) if "match_build=sub != \"status\"" in l)
    block = " ".join(l.strip() for l in lines[max(0, at - 6) : at])
    assert MARKER in block
    assert re.search(r"ceiling:.*only reads", block, re.I) and re.search(r"upgrade trigger:.*side effect", block, re.I)
    prose = " ".join(block.replace("#", " ").split())
    assert re.search(r"any file at the staged (runner )?path runs as root", prose, re.I), prose


def test_the_stage_restage_window_is_marked_where_stage_takes_the_host_lock():
    text = (PKG / "cli.py").read_text()
    at = text.index('with ctx.lock("stage")')
    block = text[max(0, at - 700) : at]
    assert MARKER in block and "detached runner" in block
    assert re.search(r"ceiling:.*not re-read", block, re.I | re.S) and re.search(r"upgrade trigger:.*lazily", block, re.I | re.S)
