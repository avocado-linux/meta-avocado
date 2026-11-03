"""Flow tests: fakes for the host and the runner; no process is started."""

import os
import stat
from types import SimpleNamespace

import pytest

from avocado_flash_tegra import FlashError, flow, rcm, workdir
from avocado_flash_tegra.runner import Interrupted

REAL_RESOLVE_CPP = flow._resolve_cpp
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
    def __init__(self, events, listing=PINNED_LINE, rc=0, raises=None, sudo_rc=0):
        self.events = events
        self.sudo_rc = sudo_rc
        self.listing = listing
        self.rc = rc
        self.raises = raises
        self.streamed = []

    def capture(self, argv):
        if argv[0] == "lsusb":
            self.events.append("list")
            return 0, f"{self.listing}\n"
        if list(argv) == ["sudo", "-v"]:
            self.events.append("sudo-v")
            return self.sudo_rc, ""
        # The success cleanup removes the root-owned tegraflash dir via sudo.
        self.events.append("cleanup")
        return 0, ""

    def stream(self, invocation, log_path, echo=print):
        self.events.append("stream")
        self.streamed.append((invocation, log_path))
        if self.raises:
            raise self.raises
        return self.rc


@pytest.fixture(autouse=True)
def as_root(monkeypatch):
    """Default caller is root; tests that need sudo override this."""
    monkeypatch.setattr(flow.os, "geteuid", lambda: 0)


@pytest.fixture
def non_root(monkeypatch):
    monkeypatch.setattr(flow.os, "geteuid", lambda: 1000)
    monkeypatch.setattr(flow.shutil, "which", lambda name, **kw: "/usr/bin/sudo")


@pytest.fixture(autouse=True)
def host_cpp(tmp_path, monkeypatch):
    """A stand-in host preprocessor so staging never depends on the machine."""
    real = tmp_path / "host-cpp-real"
    real.write_text("#!/bin/sh\n")
    real.chmod(0o755)
    monkeypatch.setattr(flow, "_resolve_cpp", lambda caller_path: str(real))
    return real


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


def test_non_root_with_sudo_runs_through_sudo(ctx, events, non_root):
    runner = FakeRunner(events)
    flow.flash(ctx, FakeHost(events), runner, assume_yes=True)
    assert runner.streamed[0][0].argv[0] == "sudo"


def test_non_root_authenticates_sudo_after_confirming_and_before_the_recheck(ctx, events, non_root):
    flow.flash(ctx, FakeHost(events), FakeRunner(events), assume_yes=False)
    assert events[:4] == ["confirm", "sudo-v", "list", "stream"]


def test_failed_sudo_authentication_never_rechecks_or_streams(ctx, events, non_root):
    runner = FakeRunner(events, sudo_rc=1)
    with pytest.raises(FlashError, match="could not obtain root: sudo authentication failed"):
        flow.flash(ctx, FakeHost(events), runner, assume_yes=False)
    assert events == ["confirm", "sudo-v"]
    assert runner.streamed == []


def test_a_refused_confirmation_never_asks_for_sudo(ctx, events, non_root):
    with pytest.raises(FlashError, match="mismatch"):
        flow.flash(ctx, FakeHost(events, fail=True), FakeRunner(events), assume_yes=False)
    assert events == ["confirm"]


def test_keyboard_interrupt_escaping_the_runner_is_reported_as_interrupted(ctx, events, capsys):
    runner = FakeRunner(events, raises=KeyboardInterrupt())
    with pytest.raises(Interrupted):
        flow.flash(ctx, FakeHost(events), runner, assume_yes=True)
    out = capsys.readouterr().out
    assert ctx.workdir.path.is_dir()
    assert "recovery mode again" in out
    assert str(ctx.workdir.path) in out and str(ctx.workdir.log) in out


def test_a_script_that_cannot_start_surfaces_as_a_flash_error_keeping_the_directory(ctx, events):
    runner = FakeRunner(events, raises=FlashError(f"cannot start x (work directory: {ctx.workdir.path})"))
    with pytest.raises(FlashError, match="cannot start"):
        flow.flash(ctx, FakeHost(events), runner, assume_yes=True)
    assert ctx.workdir.path.is_dir()


def test_root_caller_makes_no_sudo_call(ctx, events):
    flow.flash(ctx, FakeHost(events), FakeRunner(events), assume_yes=False)
    assert "sudo-v" not in events


def _foreign_owner(path):
    real = os.lstat(path)
    return SimpleNamespace(st_mode=real.st_mode, st_uid=real.st_uid + 1)


def test_stage_helper_creates_bin_private(ctx):
    bin_dir = flow._stage_helper(ctx)
    assert stat.S_IMODE(os.stat(bin_dir).st_mode) == 0o700


def test_stage_helper_replaces_a_planted_symlink_without_following_it(ctx, tmp_path):
    victim = tmp_path / "victim"
    victim.write_text("precious")
    (ctx.workdir.path / "bin").mkdir(mode=0o700)
    (ctx.workdir.path / "bin" / flow.HELPER_NAME).symlink_to(victim)
    bin_dir = flow._stage_helper(ctx)
    staged = bin_dir / flow.HELPER_NAME
    assert victim.read_text() == "precious"
    assert not staged.is_symlink()
    assert staged.read_text() == "#!/bin/sh\n"
    assert stat.S_IMODE(staged.stat().st_mode) == 0o755


def test_stage_helper_refuses_a_symlinked_bin(ctx, tmp_path):
    other = tmp_path / "other"
    other.mkdir(mode=0o700)
    (ctx.workdir.path / "bin").symlink_to(other)
    with pytest.raises(FlashError):
        flow._stage_helper(ctx)
    assert list(other.iterdir()) == []


def test_stage_helper_refuses_a_bin_owned_by_someone_else(ctx):
    (ctx.workdir.path / "bin").mkdir(mode=0o700)
    with pytest.raises(FlashError, match="owned"):
        flow._stage_helper(ctx, stat_fn=_foreign_owner)


def test_stage_helper_refuses_a_group_writable_bin(ctx):
    (ctx.workdir.path / "bin").mkdir()
    os.chmod(ctx.workdir.path / "bin", 0o770)  # nosemgrep: python.lang.security.audit.insecure-file-permissions.insecure-file-permissions - test builds an unsafe directory on purpose
    with pytest.raises(FlashError, match="writable"):
        flow._stage_helper(ctx)


def _empty_workdir(ctx):
    (ctx.workdir.path / "tegraflash").rmdir()


def test_refused_confirmation_removes_the_directory_the_tool_created(ctx, events):
    _empty_workdir(ctx)
    with pytest.raises(FlashError):
        flow.flash(ctx, FakeHost(events, fail=True), FakeRunner(events), assume_yes=False)
    assert not ctx.workdir.path.exists()


def test_changed_device_set_removes_the_staged_directory_too(ctx, events):
    _empty_workdir(ctx)
    runner = FakeRunner(events, listing=PINNED_LINE + "\n" + SECOND_LINE)
    with pytest.raises(rcm.DeviceSetChanged):
        flow.flash(ctx, FakeHost(events), runner, assume_yes=False)
    assert not ctx.workdir.path.exists()


def test_refusal_never_removes_a_directory_the_tool_did_not_create(ctx, events):
    _empty_workdir(ctx)
    ctx.workdir = workdir.Workdir(ctx.workdir.path, False)
    with pytest.raises(FlashError):
        flow.flash(ctx, FakeHost(events, fail=True), FakeRunner(events), assume_yes=False)
    assert ctx.workdir.path.is_dir()


def test_failed_script_keeps_the_directory(ctx, events):
    _empty_workdir(ctx)
    with pytest.raises(FlashError):
        flow.flash(ctx, FakeHost(events), FakeRunner(events, rc=2), assume_yes=True)
    assert ctx.workdir.path.is_dir()


# ---- the staged preprocessor alias (the script's own fallback loops) ----


def test_stage_helper_stages_a_cpp_alias_named_for_the_machine(ctx, monkeypatch, host_cpp):
    monkeypatch.setattr(flow.platform, "machine", lambda: "aarch64")
    bin_dir = flow._stage_helper(ctx)
    alias = bin_dir / "aarch64-avocadosdk-linux-cpp"
    assert alias.is_symlink()
    assert os.path.realpath(alias) == os.path.realpath(host_cpp)


def test_stage_helper_replaces_a_planted_cpp_alias_without_following_it(
    ctx, tmp_path, monkeypatch
):
    monkeypatch.setattr(flow.platform, "machine", lambda: "x86_64")
    victim = tmp_path / "victim"
    victim.write_text("precious")
    (ctx.workdir.path / "bin").mkdir(mode=0o700)
    (ctx.workdir.path / "bin" / "x86_64-avocadosdk-linux-cpp").symlink_to(victim)
    bin_dir = flow._stage_helper(ctx)
    assert victim.read_text() == "precious"
    assert os.path.realpath(bin_dir / "x86_64-avocadosdk-linux-cpp") != str(victim)


def test_resolve_cpp_returns_the_realpath_of_the_caller_path_hit(tmp_path, monkeypatch):
    real = tmp_path / "real-cpp"
    real.write_text("")
    link = tmp_path / "cpp"
    link.symlink_to(real)
    seen = {}

    def fake_which(name, path=None):
        seen["args"] = (name, path)
        return str(link)

    monkeypatch.setattr(flow.shutil, "which", fake_which)
    assert REAL_RESOLVE_CPP("/a:/b") == str(real)
    assert seen["args"] == ("cpp", "/a:/b")


def test_resolve_cpp_refuses_when_absent(monkeypatch):
    monkeypatch.setattr(flow.shutil, "which", lambda name, path=None: None)
    with pytest.raises(FlashError, match="cpp"):
        REAL_RESOLVE_CPP("/nowhere")


def test_stage_helper_looks_for_cpp_only_on_absolute_path_components(ctx, monkeypatch):
    seen = []
    monkeypatch.setenv("PATH", "/usr/bin::.:rel/bin")
    monkeypatch.setattr(flow, "_resolve_cpp", lambda caller_path: seen.append(caller_path) or "/bin/true")
    flow._stage_helper(ctx)
    assert seen == ["/usr/bin"]


def test_stage_helper_refuses_without_a_host_cpp(ctx, monkeypatch):
    def refuse(caller_path):
        raise FlashError("no C preprocessor (cpp) found")

    monkeypatch.setattr(flow, "_resolve_cpp", refuse)
    with pytest.raises(FlashError, match="cpp"):
        flow._stage_helper(ctx)


def test_discard_removes_the_alias_and_bin(ctx, monkeypatch):
    _empty_workdir(ctx)
    monkeypatch.setattr(flow.platform, "machine", lambda: "aarch64")
    flow._stage_helper(ctx)
    flow._discard_workdir(ctx)
    assert not ctx.workdir.path.exists()


def test_success_cleanup_leaves_no_alias(ctx, events, monkeypatch):
    monkeypatch.setattr(flow.platform, "machine", lambda: "aarch64")
    flow.flash(ctx, FakeHost(events), FakeRunner(events), assume_yes=True)
    assert not ctx.workdir.path.exists()


# ---- the confirmation names the target (incident 12.1-1) ----


def test_confirmation_prompt_names_the_pinned_path_before_asking(ctx, events, capsys):
    seen = {}

    class Host(FakeHost):
        def confirm_destructive(self, *a):
            seen["out"] = capsys.readouterr().out
            return super().confirm_destructive(*a)

    flow.flash(ctx, Host(events), FakeRunner(events), assume_yes=False)
    assert f"To confirm, type: {ctx.pinned.path}" in seen["out"]


def test_assume_yes_prints_no_confirm_line(ctx, events, capsys):
    flow.flash(ctx, FakeHost(events), FakeRunner(events), assume_yes=True)
    assert "To confirm, type" not in capsys.readouterr().out
