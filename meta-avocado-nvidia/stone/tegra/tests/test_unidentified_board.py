"""A board nothing identifies is refused before waiting; AVOCADO_PROVISION_RCM_ID overrides the manifest list."""

import json
import sys
from pathlib import Path

import pytest

from avocado_tegraflash.cli import main
from test_cli_flow import FakeRunner, make_rig

VAR = "AVOCADO_PROVISION_RCM_ID"
FORCE = "AVOCADO_PROVISION_FORCE"


def _drop_ids(node):
    if isinstance(node, dict):
        node.pop("rcm_ids", None)
        node.pop("rcm_evidence", None)
        for child in node.values():
            _drop_ids(child)


def _no_ids(rig):
    """Remove the manifest's rcm_ids, leaving a manifest that declares no board id."""
    path = Path(rig.environ["AVOCADO_STONE_MANIFEST"])
    doc = json.loads(path.read_text())
    _drop_ids(doc)
    path.write_text(json.dumps(doc))
    return rig


def _terminal(monkeypatch, tty, answer="001:005"):
    monkeypatch.setattr(sys.stdin, "isatty", lambda: tty)
    monkeypatch.setattr("builtins.input", lambda prompt="": answer)


def _refused_early(rig, rc, err) -> bool:
    # The adb warm-up precedes the manifest read in the oracle's order, so it may have run.
    board_contact = {"lsusb", "boardctl", "initrd-flash"}
    return rc != 0 and VAR in err and not rig.work.exists() and not board_contact & set(rig.runner.tools())


def test_force_one_with_no_id_is_refused_before_waiting(tmp_path, capsys):
    rig = _no_ids(make_rig(tmp_path, env={FORCE: "1"}))
    rc, _, err = rig.go(main, capsys)
    assert _refused_early(rig, rc, err)


def test_refusal_applies_under_prepare_only(tmp_path, capsys):
    rig = _no_ids(make_rig(tmp_path, env={FORCE: "1"}))
    rc, _, err = rig.go(main, capsys, argv=["--prepare-only"])
    assert _refused_early(rig, rc, err)


def test_unset_force_without_a_terminal_is_refused_the_same_way(tmp_path, capsys, monkeypatch):
    _terminal(monkeypatch, False)
    rig = _no_ids(make_rig(tmp_path))
    del rig.environ[FORCE]
    rc, _, err = rig.go(main, capsys)
    assert _refused_early(rig, rc, err)


def test_force_zero_on_a_terminal_warns_and_retypes(tmp_path, capsys, monkeypatch):
    _terminal(monkeypatch, True)
    rig = _no_ids(make_rig(tmp_path, env={FORCE: "0"}))
    rc, out, _ = rig.go(main, capsys)
    assert (rc, "not identity-checked" in out, len(rig.runner.named("initrd-flash"))) == (0, True, 1)


def test_force_zero_without_a_terminal_keeps_the_confirm_refusal(tmp_path, capsys, monkeypatch):
    _terminal(monkeypatch, False)
    rig = _no_ids(make_rig(tmp_path, env={FORCE: "0"}))
    rc, _, err = rig.go(main, capsys)
    assert (rc, "requires confirmation" in err, rig.runner.named("initrd-flash")) == (1, True, [])


def test_override_supplies_the_id_a_manifest_lacks(tmp_path, capsys):
    rig = _no_ids(make_rig(tmp_path, env={FORCE: "1", VAR: "0955:7523"}))
    rc, out, _ = rig.go(main, capsys)
    assert (rc, "not identity-checked" in out, len(rig.runner.named("initrd-flash"))) == (0, False, 1)


def test_override_replaces_the_manifest_list_at_the_wait(tmp_path, capsys):
    rig = make_rig(tmp_path, env={VAR: "0955:7c18"})
    rc, _, err = rig.go(main, capsys)
    assert (rc, "0955:7c18" in err, rig.runner.named("initrd-flash")) == (1, True, [])


def test_override_matching_the_board_flashes(tmp_path, capsys):
    line = "Bus 001 Device 005: ID 0955:7c18 NVIDIA Corp. APX"
    rig = make_rig(tmp_path, env={VAR: "0955:7c18"}, runner=FakeRunner(lsusb=[[line]]))
    rc, _, _ = rig.go(main, capsys)
    assert (rc, len(rig.runner.named("initrd-flash"))) == (0, 1)


@pytest.mark.parametrize(
    "bad",
    ["0955:7C18", "0x0955:0x7523", " 0955:7523", "0955:7523 ", "0955-7523", "955:7523", "0955:75234", "0955:7523,0955:7c18", "0955:7523\n"],
)
def test_a_malformed_override_is_refused_before_anything_is_staged(tmp_path, capsys, bad):
    rig = make_rig(tmp_path, env={VAR: bad})
    rc, _, err = rig.go(main, capsys)
    assert _refused_early(rig, rc, err)


def test_a_malformed_override_is_refused_under_prepare_only(tmp_path, capsys):
    rig = make_rig(tmp_path, env={VAR: "0955:7C18"})
    rc, _, err = rig.go(main, capsys, argv=["--prepare-only"])
    assert _refused_early(rig, rc, err)


def test_force_one_with_manifest_ids_still_waits(tmp_path, capsys):
    rig = make_rig(tmp_path, env={FORCE: "1"})
    rc, _, _ = rig.go(main, capsys)
    assert (rc, "lsusb" in rig.runner.tools()) == (0, True)


def test_an_empty_override_is_no_override_and_the_manifest_ids_still_apply(tmp_path, capsys):
    # Empty counts as unset, as for FORCE, FWUP_TASK and DRY_RUN: a manifest id that
    # the board does not match must still refuse, so the manifest list was used.
    line = "Bus 001 Device 005: ID 0955:7c18 NVIDIA Corp. APX"
    rig = make_rig(tmp_path, env={VAR: ""}, runner=FakeRunner(lsusb=[[line]]))
    rc, _, err = rig.go(main, capsys)
    assert (rc, "must be a lowercase" in err, "0955:7523" in err, rig.runner.named("initrd-flash")) == (1, False, True, [])


def test_an_empty_override_does_not_supply_an_id_a_manifest_lacks(tmp_path, capsys):
    rig = _no_ids(make_rig(tmp_path, env={FORCE: "1", VAR: ""}))
    rc, _, err = rig.go(main, capsys)
    assert (_refused_early(rig, rc, err), "must be a lowercase" in err) == (True, False)
