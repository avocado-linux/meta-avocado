"""Flow tests: fakes for the host and the runner; no process is started."""

import stat

import pytest

from avocado_flash_tegra import FlashError, InputInfo, flow, rcm, workdir
from avocado_flash_tegra.runner import Interrupted

PINNED_LINE = "Bus 001 Device 004: ID 0955:7523 NVIDIA Corp. APX"
SECOND_LINE = "Bus 001 Device 005: ID 0955:7523 NVIDIA Corp. APX"


class FakeFatal(Exception):
    pass


class FakeHost:
    def __init__(self, events, fail=False):
        self.events = events
        self.fail = fail
        self.calls = []
        self.fatal = FakeFatal

    def confirm_destructive(self, target, payload, dry_run, assume_yes):
        self.calls.append((target, payload, dry_run, assume_yes))
        self.events.append("confirm")
        if self.fail:
            raise FakeFatal("mismatch, aborting")


class FakeRunner:
    def __init__(self, events, listing=PINNED_LINE, rc=0, raises=None):
        self.events = events
        self.listing = listing
        self.rc = rc
        self.raises = raises
        self.streamed = []

    def capture(self, argv):
        if argv[0] == "lsusb":
            self.events.append("list")
            return 0, f"{self.listing}\n"
        # The success cleanup removes the root-owned tegraflash dir via sudo.
        self.events.append("cleanup")
        return 0, ""

    def stream(self, invocation, log_path, echo=print):
        self.events.append("stream")
        self.streamed.append((invocation, log_path))
        if self.raises:
            raise self.raises
        return self.rc


@pytest.fixture
def events():
    return []


@pytest.fixture
def ctx(tmp_path):
    helper = tmp_path / "src-helper"
    helper.write_text("#!/bin/sh\n")
    helper.chmod(0o644)
    images = tmp_path / "images"
    images.mkdir()
    wd = workdir.create_workdir(tmp_path / "work")
    (wd.path / "tegraflash").mkdir()
    pinned = rcm.UsbDevice("001", "004", "0955", "7523", "NVIDIA Corp. APX")
    return flow.FlashContext(
        machine="avocado-jetson-orin-nano",
        images_dir=images,
        manifest=images / "manifest.json",
        script=images / "provision.sh",
        kernel_image=images / "Image",
        helper_source=helper,
        extra_path_dir=None,
        expected_id="0955:7523",
        pinned=pinned,
        infos=[InputInfo("manifest", "m", 10, 0.0)],
        workdir=wd,
    )


def test_confirmation_then_recheck_then_stream(ctx, events):
    host = FakeHost(events)
    runner = FakeRunner(events)
    flow.flash(ctx, host, runner, assume_yes=False)
    assert events[:3] == ["confirm", "list", "stream"]
    assert host.calls[0][0] == "001:004"
    assert host.calls[0][2:] == (False, False)


def test_wrong_retype_never_reaches_stream(ctx, events):
    host = FakeHost(events, fail=True)
    runner = FakeRunner(events)
    with pytest.raises(FlashError, match="mismatch"):
        flow.flash(ctx, host, runner, assume_yes=False)
    assert events == ["confirm"]
    assert runner.streamed == []


def test_assume_yes_prints_warning_and_never_asks(ctx, events, capsys):
    host = FakeHost(events)
    runner = FakeRunner(events)
    flow.flash(ctx, host, runner, assume_yes=True)
    out = capsys.readouterr().out
    assert host.calls == []
    assert "erased" in out
    assert "QSPI firmware" in out and "UEFI variables" in out
    assert "cannot be read in recovery mode" in out
    assert events[:2] == ["list", "stream"]


def test_warning_is_printed_before_the_confirmation(ctx, events, capsys):
    class Host(FakeHost):
        def confirm_destructive(self, *a):
            self.seen = capsys.readouterr().out
            super().confirm_destructive(*a)

    host = Host(events)
    flow.flash(ctx, host, FakeRunner(events), assume_yes=False)
    assert "erased" in host.seen


def test_second_board_at_recheck_never_reaches_stream(ctx, events):
    host = FakeHost(events)
    runner = FakeRunner(events, listing=PINNED_LINE + "\n" + SECOND_LINE)
    with pytest.raises(rcm.DeviceSetChanged):
        flow.flash(ctx, host, runner, assume_yes=False)
    assert runner.streamed == []
    assert events == ["confirm", "list"]


def test_vanished_board_at_recheck_never_reaches_stream(ctx, events):
    runner = FakeRunner(events, listing="Bus 001 Device 001: ID 1d6b:0002 hub")
    with pytest.raises(rcm.DeviceSetChanged):
        flow.flash(ctx, FakeHost(events), runner, assume_yes=False)
    assert runner.streamed == []


def test_helper_dir_leads_path_and_log_goes_to_workdir(ctx, events):
    runner = FakeRunner(events)
    flow.flash(ctx, FakeHost(events), runner, assume_yes=True)
    invocation, log_path = runner.streamed[0]
    assert invocation.env["PATH"].split(":")[0] == str(ctx.workdir.path / "bin")
    assert log_path == ctx.workdir.log


def test_staged_helper_has_mode_0755(ctx, events):
    # Not created by the tool, so the success cleanup leaves it for inspection.
    ctx.workdir = workdir.Workdir(ctx.workdir.path, False)
    flow.flash(ctx, FakeHost(events), FakeRunner(events), assume_yes=True)
    staged = ctx.workdir.path / "bin" / "avocado-tegra-bootimg"
    assert stat.S_IMODE(staged.stat().st_mode) == 0o755
    assert staged.read_text() == "#!/bin/sh\n"


def test_success_removes_work_directory_after_advice(ctx, events, capsys, monkeypatch):
    seen = {}
    real = workdir.cleanup

    def spy(wd, success, runner, is_root):
        seen["out"] = capsys.readouterr().out
        seen["success"] = success
        return real(wd, success, runner, is_root)

    monkeypatch.setattr(flow.workdir, "cleanup", spy)
    flow.flash(ctx, FakeHost(events), FakeRunner(events), assume_yes=True)
    assert seen["success"] is True
    assert "FC_REC" in seen["out"] and "power-cycle" in seen["out"]
    assert not ctx.workdir.path.exists()


def test_failure_keeps_work_directory_and_prints_paths(ctx, events, capsys):
    runner = FakeRunner(events, rc=3)
    with pytest.raises(FlashError):
        flow.flash(ctx, FakeHost(events), runner, assume_yes=True)
    out = capsys.readouterr().out
    assert ctx.workdir.path.is_dir()
    assert str(ctx.workdir.path) in out
    assert str(ctx.workdir.log) in out
    assert "recovery mode again" in out


def test_interrupt_keeps_work_directory_and_reraises(ctx, events, capsys):
    runner = FakeRunner(events, raises=Interrupted("interrupted"))
    with pytest.raises(Interrupted):
        flow.flash(ctx, FakeHost(events), runner, assume_yes=True)
    out = capsys.readouterr().out
    assert ctx.workdir.path.is_dir()
    assert str(ctx.workdir.path) in out
    assert "recovery mode again" in out


def test_non_root_with_sudo_runs_through_sudo(ctx, events, monkeypatch):
    monkeypatch.setattr(flow.os, "geteuid", lambda: 1000)
    monkeypatch.setattr(flow.shutil, "which", lambda name: "/usr/bin/sudo")
    runner = FakeRunner(events)
    flow.flash(ctx, FakeHost(events), runner, assume_yes=True)
    assert runner.streamed[0][0].argv[0] == "sudo"
