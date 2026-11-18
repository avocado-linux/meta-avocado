"""AVOCADO_PROVISION_DRY_RUN=1 is --prepare-only; other values and a non-complete FWUP_TASK are refused."""

import pytest

from avocado_tegraflash.cli import main
from test_cli_flow import make_rig

DRY = "AVOCADO_PROVISION_DRY_RUN"
TASK = "AVOCADO_PROVISION_FWUP_TASK"
BOARD_CONTACT = {"lsusb", "boardctl", "initrd-flash"}


def test_dry_run_one_skips_the_root_check_and_contacts_no_board(tmp_path, capsys):
    rig = make_rig(tmp_path, env={DRY: "1"})
    rc, out, _ = rig.go(main, capsys, euid=1000)
    assert (rc, "Work directory:" in out, BOARD_CONTACT & set(rig.runner.tools())) == (0, True, set())


def test_dry_run_one_never_prompts(tmp_path, capsys, monkeypatch):
    def boom(prompt=""):
        raise AssertionError("prompted")

    monkeypatch.setattr("builtins.input", boom)
    rig = make_rig(tmp_path, env={DRY: "1", "AVOCADO_PROVISION_FORCE": "0"})
    rc, _, _ = rig.go(main, capsys, euid=1000)
    assert rc == 0


@pytest.mark.parametrize("value", ["0", "true", "yes", "2", " 1"])
def test_other_dry_run_values_are_refused_naming_variable_and_value(tmp_path, capsys, value):
    rig = make_rig(tmp_path, env={DRY: value})
    rc, _, err = rig.go(main, capsys)
    assert (rc != 0, DRY in err, repr(value) in err, rig.work.exists(), rig.runner.calls) == (True, True, True, False, [])


def test_empty_dry_run_is_a_normal_run(tmp_path, capsys):
    rig = make_rig(tmp_path, env={DRY: ""})
    rc, _, err = rig.go(main, capsys, euid=1000)
    assert (rc, "root is required" in err) == (1, True)


@pytest.mark.parametrize("env", [{}, {TASK: ""}, {TASK: "complete"}])
def test_task_unset_empty_or_complete_runs(tmp_path, capsys, env):
    rig = make_rig(tmp_path, env=env)
    rc, _, _ = rig.go(main, capsys)
    assert rc == 0


@pytest.mark.parametrize("argv", [[], ["--prepare-only"]])
def test_task_upgrade_is_refused_before_staging(tmp_path, capsys, argv):
    rig = make_rig(tmp_path, env={TASK: "upgrade"})
    rc, _, err = rig.go(main, capsys, argv=argv)
    assert (rc != 0, TASK in err, "'upgrade'" in err, rig.work.exists(), rig.runner.calls) == (True, True, True, False, [])


def test_dry_run_runs_the_board_free_refusals(tmp_path, capsys):
    rig = make_rig(tmp_path, unpinned_ok=False, env={DRY: "1"})
    rc, _, err = rig.go(main, capsys)
    assert (rc != 0, "AVOCADO_PROVISION_KERNEL_IMAGE" in err, rig.work.exists()) == (True, True, False)


def test_dry_run_with_a_missing_rootfs_image_is_refused_like_a_real_run(tmp_path, capsys):
    rig = make_rig(tmp_path, drop=("rootfs",), env={DRY: "1"})
    rc, _, err = rig.go(main, capsys)
    real = make_rig(tmp_path / "real", drop=("rootfs",))
    rrc, _, rerr = real.go(main, capsys)
    assert (rc, "unusable" in err, rig.runner.tools()) == (rrc, "unusable" in rerr, real.runner.tools())
    assert rc != 0 and "unusable" in err
