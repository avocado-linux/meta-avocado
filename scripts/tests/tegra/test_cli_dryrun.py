"""CLI tests: fakes for the host and the runner; no process is started."""

import os
import shutil

import pytest

from avocado_flash_tegra import cli

BOARD = "Bus 001 Device 004: ID 0955:7523 NVIDIA Corp. APX"


class FakeFatal(Exception):
    pass


class FakeRunner:
    def __init__(self, listing=BOARD):
        self.listing = listing
        self.captured = []
        self.streamed = []

    def capture(self, argv):
        self.captured.append(list(argv))
        return 0, f"{self.listing}\n" if self.listing else ""

    def stream(self, invocation, log_path, echo=print):
        self.streamed.append(invocation)
        return 0


def make_host(tree, confirmed=None):
    deploy = tree.images_dir.parent.parent

    def confirm(target, payload, dry_run, assume_yes):
        if confirmed is not None:
            confirmed.append((target, payload))

    return cli.Host(
        resolve_deploy_dir=lambda explicit: explicit or deploy,
        resolve_machine=lambda d, explicit: explicit or tree.machine,
        confirm_destructive=confirm,
        fatal=FakeFatal,
    )


@pytest.fixture(autouse=True)
def tools_present(monkeypatch):
    """Every host tool, and sudo, resolves; the caller is not root."""
    monkeypatch.setattr(shutil, "which", lambda name, path=None: f"/stub/{name}")
    monkeypatch.setattr(os, "geteuid", lambda: 1000)


def run(tree, tmp_path, extra, runner=None, host=None):
    runner = runner or FakeRunner()
    argv = ["--deploy", str(tree.images_dir.parent.parent), "--workdir", str(tmp_path / "work"), *extra]
    rc = cli.main(argv, host or make_host(tree), runner)
    return rc, runner


def test_dry_run_with_one_board_prints_every_item_and_runs_only_lsusb(deploy_tree, tmp_path, capsys):
    rc, runner = run(deploy_tree, tmp_path, ["--dry-run"])
    out = capsys.readouterr().out
    assert rc == 0
    assert runner.captured == [["lsusb"]]
    assert runner.streamed == []
    assert "inputs: all present" in out
    assert "pinned: 001:004 0955:7523" in out
    assert deploy_tree.machine in out
    assert str(deploy_tree.images_dir.parent.parent) in out
    assert str(deploy_tree.template) in out
    assert "avocado-tegra-bootimg" in out
    assert str(tmp_path / "work") in out
    assert "AVOCADO_PROVISION_PROFILE=tegraflash-nvme" in out
    assert "command:" in out
    assert out.index("inputs: all present") < out.index("pinned:")
    assert not (tmp_path / "work").exists()


def test_dry_run_prints_one_line_per_input_before_the_usb_listing(deploy_tree, tmp_path, capsys):
    rc, _ = run(deploy_tree, tmp_path, ["--dry-run"])
    out = capsys.readouterr().out
    assert rc == 0
    assert deploy_tree.script.name not in out.split("inputs: all present")[0]
    assert "Image" not in out.split("inputs: all present")[0]
    after = out.split("inputs: all present", 1)[1].split("pinned:", 1)[0]
    assert "avocado-image-var" in after


def test_dry_run_with_a_missing_input_refuses_and_runs_nothing(deploy_tree, tmp_path, capsys):
    (deploy_tree.images_dir / "tegra-espimage-avocado-jetson-orin-nano.esp").unlink()
    rc, runner = run(deploy_tree, tmp_path, ["--dry-run"])
    captured = capsys.readouterr()
    assert rc == 1
    assert runner.captured == []
    assert "avocado-flash:" in captured.err
    assert "tegra-espimage" in captured.err
    assert "inputs: all present" not in captured.out


def test_dry_run_reports_a_missing_host_tool_in_the_same_message(deploy_tree, tmp_path, capsys, monkeypatch):
    real = lambda name, path=None: None if name in ("jq", "mkbootimg") else f"/stub/{name}"  # noqa: E731
    monkeypatch.setattr(shutil, "which", real)
    (deploy_tree.images_dir / "tegra-espimage-avocado-jetson-orin-nano.esp").unlink()
    rc, runner = run(deploy_tree, tmp_path, ["--dry-run"])
    err = capsys.readouterr().err
    assert rc == 1
    assert runner.captured == []
    assert "jq" in err
    assert "mkbootimg" in err
    assert "tegra-espimage" in err


def test_dry_run_with_no_board_prints_inputs_then_refuses(deploy_tree, tmp_path, capsys):
    rc, runner = run(deploy_tree, tmp_path, ["--dry-run"], runner=FakeRunner(listing=""))
    captured = capsys.readouterr()
    assert rc == 1
    assert runner.captured == [["lsusb"]]
    assert "inputs: all present" in captured.out
    assert "pinned:" not in captured.out
    assert "no NVIDIA device in recovery mode" in captured.err
    assert not (tmp_path / "work").exists()


def test_dry_run_without_root_or_sudo_refuses_before_lsusb(deploy_tree, tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda name, path=None: None if name == "sudo" else f"/stub/{name}")
    rc, runner = run(deploy_tree, tmp_path, ["--dry-run"])
    captured = capsys.readouterr()
    assert rc == 1
    assert runner.captured == []
    assert "the flash needs root: run as root or install sudo" in captured.err
    assert "inputs: all present" not in captured.out


def test_missing_sudo_is_reported_together_with_the_other_problems(deploy_tree, tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda name, path=None: None if name == "sudo" else f"/stub/{name}")
    (deploy_tree.images_dir / "tegra-espimage-avocado-jetson-orin-nano.esp").unlink()
    rc, runner = run(deploy_tree, tmp_path, ["--dry-run"])
    err = capsys.readouterr().err
    assert rc == 1
    assert runner.captured == []
    assert "install sudo" in err
    assert "tegra-espimage" in err


def test_dry_run_as_root_without_sudo_proceeds(deploy_tree, tmp_path, monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda name, path=None: None if name == "sudo" else f"/stub/{name}")
    monkeypatch.setattr(os, "geteuid", lambda: 0)
    rc, runner = run(deploy_tree, tmp_path, ["--dry-run"])
    assert rc == 0
    assert runner.captured == [["lsusb"]]


def test_assume_yes_real_run_prints_the_pinned_line_and_streams(deploy_tree, tmp_path, capsys):
    confirmed = []
    rc, runner = run(deploy_tree, tmp_path, ["-y"], host=make_host(deploy_tree, confirmed))
    out = capsys.readouterr().out
    assert rc == 0
    assert "pinned: 001:004 0955:7523" in out
    assert len(runner.streamed) == 1
    assert confirmed == []


def test_real_run_without_yes_asks_for_confirmation(deploy_tree, tmp_path):
    confirmed = []
    rc, runner = run(deploy_tree, tmp_path, [], host=make_host(deploy_tree, confirmed))
    assert rc == 0
    assert len(confirmed) == 1


@pytest.mark.parametrize(
    "extra",
    [["--task", "upgrade"], ["/dev/whatever"], ["--stale-ok"], ["--dry-run", "--task=upgrade"]],
)
def test_foreign_option_or_device_argument_exits_2_without_calling_the_runner(deploy_tree, tmp_path, extra):
    rc, runner = run(deploy_tree, tmp_path, extra)
    assert rc == 2
    assert runner.captured == []


def test_dry_run_with_a_malformed_rcm_id_is_refused_before_the_runner(deploy_tree, tmp_path, capsys):
    rc, runner = run(deploy_tree, tmp_path, ["--dry-run", "--rcm-id", "zzzz"])
    assert rc == 1
    assert runner.captured == []
    assert "invalid --rcm-id" in capsys.readouterr().err


def test_dry_run_creates_no_work_directory_under_the_default_base(deploy_tree, tmp_path):
    argv = ["--deploy", str(deploy_tree.images_dir.parent.parent), "--dry-run"]
    def mine():
        return {n for n in os.listdir("/var/tmp") if n.startswith("avocado-flash-")}

    before = mine()
    rc = cli.main(argv, make_host(deploy_tree), FakeRunner())
    assert rc == 0
    assert mine() == before


def test_interrupted_run_returns_130(deploy_tree, tmp_path):
    from avocado_flash_tegra.runner import Interrupted

    class Raising(FakeRunner):
        def stream(self, invocation, log_path, echo=print):
            raise Interrupted("interrupted")

    rc, _ = run(deploy_tree, tmp_path, ["-y"], runner=Raising())
    assert rc == 130


def test_host_fatal_is_reported_and_returns_1(deploy_tree, tmp_path, capsys):
    host = make_host(deploy_tree)

    def boom(explicit):
        raise FakeFatal("no deploy here")

    host.resolve_deploy_dir = boom
    rc, runner = run(deploy_tree, tmp_path, ["--dry-run"], host=host)
    assert rc == 1
    assert "avocado-flash: no deploy here" in capsys.readouterr().err
    assert runner.captured == []


def test_keyboard_interrupt_returns_130_with_a_message(deploy_tree, tmp_path, capsys):
    class Raising(FakeRunner):
        def capture(self, argv):
            raise KeyboardInterrupt

    rc, _ = run(deploy_tree, tmp_path, ["--dry-run"], runner=Raising())
    assert rc == 130
    assert "avocado-flash: interrupted" in capsys.readouterr().err


def test_closed_stdin_at_the_confirmation_returns_1_with_advice(deploy_tree, tmp_path, capsys):
    host = make_host(deploy_tree)

    def eof(target, payload, dry_run, assume_yes):
        raise EOFError

    host.confirm_destructive = eof
    rc, runner = run(deploy_tree, tmp_path, [], host=host)
    err = capsys.readouterr().err
    assert rc == 1
    assert runner.streamed == []
    assert "no terminal to read the confirmation from; pass --assume-yes to skip it" in err


def _edit_template(tree, edit):
    import json

    data = json.loads(tree.template.read_text())
    edit(data)
    tree.template.write_text(json.dumps(data))


def test_template_profile_without_script_is_a_problem_not_a_key_error(deploy_tree, tmp_path, capsys):
    _edit_template(deploy_tree, lambda d: d["provision"]["profiles"]["tegraflash-nvme"].pop("script"))
    rc, runner = run(deploy_tree, tmp_path, ["--dry-run"])
    err = capsys.readouterr().err
    assert rc == 1
    assert runner.captured == []
    assert "script" in err and "avocado-stone" in err
    assert "Traceback" not in err


def test_template_without_tegraflash_tools_is_a_problem_not_a_key_error(deploy_tree, tmp_path, capsys):
    _edit_template(
        deploy_tree,
        lambda d: d["storage_devices"]["rootdisk"]["images"].pop("tegraflash_tools"),
    )
    rc, runner = run(deploy_tree, tmp_path, ["--dry-run"])
    err = capsys.readouterr().err
    assert rc == 1
    assert "tegraflash_tools" in err and "avocado-stone" in err


def test_relative_workdir_reaches_the_script_as_absolute_paths(deploy_tree, tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    argv = ["--deploy", str(deploy_tree.images_dir.parent.parent), "--dry-run", "--workdir", "rel-work"]
    assert cli.main(argv, make_host(deploy_tree), FakeRunner()) == 0
    out = capsys.readouterr().out
    want = tmp_path / "rel-work"
    assert f"AVOCADO_STONE_BUILD_DIR={want}\n" in out
    assert f"PATH={want}/bin:" in out


def test_default_workdir_is_created_new_and_refused_when_it_exists(deploy_tree, tmp_path, monkeypatch):
    base = tmp_path / "base"
    base.mkdir()
    real = cli.workdir.planned_workdir
    monkeypatch.setattr(
        cli.workdir, "planned_workdir", lambda explicit, machine: real(explicit, machine, base=base)
    )
    argv = ["--deploy", str(deploy_tree.images_dir.parent.parent), "-y"]
    assert cli.main(argv, make_host(deploy_tree), FakeRunner()) == 0
    # A pre-created default path (what an attacker would plant) is never reused.
    planted = base / "planted"
    planted.mkdir(mode=0o700)
    monkeypatch.setattr(cli.workdir, "planned_workdir", lambda explicit, machine: planted)
    assert cli.main(argv, make_host(deploy_tree), FakeRunner()) == 1
