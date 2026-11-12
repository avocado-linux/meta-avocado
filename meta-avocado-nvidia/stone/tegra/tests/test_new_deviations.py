"""One end-to-end test per deviation added by the provisioning-parity change.

Each drives cli.main() through the shared rig with fakes. The unit-level
behaviour sits in the module tests (test_path_filter, test_unpinned_kernel,
test_unidentified_board, test_dry_run_task, test_bootimg, test_confirm); these
carry the markers test_deviations_listed.py requires.
"""

import json
import os
import sys
from pathlib import Path

import pytest

from avocado_tegraflash.cli import main
from test_cli_flow import make_rig

KERNEL = "AVOCADO_PROVISION_KERNEL_IMAGE"
OPT_OUT = "AVOCADO_PROVISION_ALLOW_UNPINNED_KERNEL"
RCM_ID = "AVOCADO_PROVISION_RCM_ID"
FORCE = "AVOCADO_PROVISION_FORCE"
DRY = "AVOCADO_PROVISION_DRY_RUN"
TASK = "AVOCADO_PROVISION_FWUP_TASK"
BOARD_CONTACT = {"lsusb", "boardctl", "initrd-flash"}


def _strip_ids(node):
    if isinstance(node, dict):
        node.pop("rcm_ids", None)
        node.pop("rcm_evidence", None)
        for child in node.values():
            _strip_ids(child)


def _manifest_without_ids(rig):
    path = Path(rig.environ["AVOCADO_STONE_MANIFEST"])
    doc = json.loads(path.read_text())
    _strip_ids(doc)
    path.write_text(json.dumps(doc))


@pytest.mark.deviation("path-filter")
def test_relative_and_empty_path_components_never_reach_the_flash_environment(tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    rig = make_rig(tmp_path)
    rig.environ["PATH"] = f"rel::./bin:{rig.stub_dir}:/usr/bin:/bin"
    rc, out, err = rig.go(main, capsys)
    (flash,) = rig.runner.named("initrd-flash")
    parts = flash.env["PATH"].split(":")
    dropped = next(l for l in (out + err).splitlines() if "dropped" in l)
    assert (rc, [p for p in parts if not os.path.isabs(p)], "'rel'" in dropped, "'./bin'" in dropped) == (0, [], True, True)


@pytest.mark.deviation("unpinned-kernel-refused")
def test_an_unpinned_kernel_is_refused_before_staging_or_board_contact(tmp_path, capsys):
    rig = make_rig(tmp_path, unpinned_ok=False)
    rc, _, err = rig.go(main, capsys)
    assert (rc != 0, KERNEL in err, OPT_OUT in err, rig.work.exists(), rig.runner.calls) == (True, True, True, False, [])


@pytest.mark.deviation("unidentified-board-refused")
def test_a_board_nothing_identifies_is_refused_before_waiting(tmp_path, capsys):
    rig = make_rig(tmp_path, env={FORCE: "1"})
    _manifest_without_ids(rig)
    rc, _, err = rig.go(main, capsys)
    assert (rc != 0, RCM_ID in err, rig.work.exists(), BOARD_CONTACT & set(rig.runner.tools())) == (True, True, False, set())


@pytest.mark.deviation("rcm-id-override")
def test_the_override_id_replaces_the_manifest_list_at_the_wait(tmp_path, capsys):
    rig = make_rig(tmp_path, env={RCM_ID: "0955:7c18"})
    rc, _, err = rig.go(main, capsys)
    assert (rc, "0955:7c18" in err, rig.runner.named("initrd-flash")) == (1, True, [])


@pytest.mark.deviation("rcm-id-override")
def test_a_malformed_override_is_refused_before_anything_is_staged(tmp_path, capsys):
    rig = make_rig(tmp_path, env={RCM_ID: "0955:7C18"})
    rc, _, err = rig.go(main, capsys)
    assert (rc != 0, RCM_ID in err, rig.work.exists(), rig.runner.calls) == (True, True, False, [])


@pytest.mark.deviation("dry-run-env-prepare-only")
def test_dry_run_one_prepares_without_root_or_board_contact(tmp_path, capsys):
    rig = make_rig(tmp_path, env={DRY: "1"})
    rc, out, _ = rig.go(main, capsys, euid=1000)
    assert (rc, "Work directory:" in out, BOARD_CONTACT & set(rig.runner.tools())) == (0, True, set())


@pytest.mark.deviation("dry-run-env-prepare-only")
def test_another_dry_run_value_is_refused_naming_variable_and_value(tmp_path, capsys):
    rig = make_rig(tmp_path, env={DRY: "yes"})
    rc, _, err = rig.go(main, capsys)
    assert (rc != 0, DRY in err, "'yes'" in err, rig.work.exists(), rig.runner.calls) == (True, True, True, False, [])


@pytest.mark.deviation("fwup-task-refused")
def test_a_non_complete_firmware_update_task_is_refused_before_staging(tmp_path, capsys):
    rig = make_rig(tmp_path, env={TASK: "upgrade"})
    rc, _, err = rig.go(main, capsys)
    assert (rc != 0, TASK in err, "'upgrade'" in err, rig.work.exists(), rig.runner.calls) == (True, True, True, False, [])


@pytest.mark.deviation("boot-tools-from-tools-dir")
def test_the_repack_starts_the_boot_helper_from_the_tools_directory_not_the_path(tmp_path, capsys):
    rig = make_rig(tmp_path, kernel=True)
    decoy = tmp_path / "decoy"
    decoy.mkdir()
    for name in ("avocado-tegra-bootimg", "mkbootimg"):
        (decoy / name).write_text("#!/bin/sh\nexit 0\n")
        (decoy / name).chmod(0o755)
    rig.environ["PATH"] = f"{decoy}:{rig.environ['PATH']}"
    rc, _, _ = rig.go(main, capsys)
    (repack,) = rig.runner.named("avocado-tegra-bootimg")
    mkbootimg = [a for a in repack.argv if Path(a).name == "mkbootimg"]
    assert rc == 0
    assert os.path.isabs(repack.argv[0]) and not repack.argv[0].startswith(str(decoy))
    assert mkbootimg and not mkbootimg[0].startswith(str(decoy))


@pytest.mark.deviation("force-policy-table")
@pytest.mark.parametrize(
    "force,tty,flashes",
    [("1", False, True), ("0", True, True), ("0", False, False), (None, False, True), ("", False, True), ("2", True, False)],
)
def test_the_force_decision_table_end_to_end(tmp_path, capsys, monkeypatch, force, tty, flashes):
    monkeypatch.setattr(sys.stdin, "isatty", lambda: tty)
    monkeypatch.setattr("builtins.input", lambda prompt="": "001:005")
    rig = make_rig(tmp_path)
    if force is None:
        del rig.environ[FORCE]
    else:
        rig.environ[FORCE] = force
    rc, _, err = rig.go(main, capsys)
    assert (rc == 0, len(rig.runner.named("initrd-flash"))) == ((True, 1) if flashes else (False, 0))
    if not flashes:
        assert FORCE in err
