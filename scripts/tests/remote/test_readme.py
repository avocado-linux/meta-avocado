"""The README is written from the code: names it documents must exist in the code."""

import pathlib
import re
import sys

SCRIPTS = pathlib.Path(__file__).resolve().parents[2]
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from avocado_flash_remote import host, state  # noqa: E402

README = (SCRIPTS / "avocado_flash_remote" / "README.md").read_text()


def _section(title):
    m = re.search(rf"^#+ {re.escape(title)}[^\n]*\n(.*?)(?=^#+ |\Z)", README, re.S | re.M)
    assert m, f"README has no section {title!r}"
    return m.group(1)


def _table_first_cells(text):
    return {m.group(1) for m in re.finditer(r"^\| `([^`]+)` \|", text, re.M)}


def test_every_phase_has_a_row_in_the_recovery_table():
    rows = _table_first_cells(_section("Run state and recovery"))
    missing = [p for p in state.PHASES if p not in rows]
    assert not missing, f"phases missing from the README recovery table: {missing}"


def test_phase_order_line_names_every_phase():
    text = _section("Run state and recovery")
    missing = [p for p in state.PHASES if f"`{p}`" not in text]
    assert not missing


def test_every_recovery_action_is_named():
    text = _section("Run state and recovery")
    missing = [a for a in set(state.RECOVERY.values()) if f"`{a}`" not in text]
    assert not missing, missing


def test_accepted_marker_is_documented_by_its_code_name():
    assert host.ACCEPTED_MARKER == "accepted"
    assert f"`{host.ACCEPTED_MARKER}`" in README


def test_exit_2_meaning_covers_connection_drop_for_the_four_subcommands():
    text = _section("Exit codes")
    assert "connection" in text and "dropped" in text
    for sub in ("check", "status", "readback", "restore"):
        assert f"`{sub}`" in text, sub


def test_extension_pinning_instructions():
    text = _section("Pinning the eMMC serial")
    for needle in ("--extension-dir", "serial", "sysfs_attr", "target-identity", "checks", "0x0badc0de"):
        assert needle in text, needle


def test_readme_has_no_em_or_en_dashes():
    assert "—" not in README and "–" not in README
