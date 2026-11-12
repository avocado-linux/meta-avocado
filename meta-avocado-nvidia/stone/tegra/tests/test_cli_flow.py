"""The whole flow through `main`, with a recording fake Runner (no tools, no root)."""

import contextlib
import importlib
import re
import subprocess
import sys
import time
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from avocado_tegraflash.cli import main
from parity.cases import APX, STONE_DIR
from parity.fixtures import build_tree
from parity.stubs import write_stubs

PACKAGE_DIR = Path(__file__).resolve().parents[1] / "avocado_tegraflash"
APX2 = "Bus 001 Device 006: ID 0955:7523 NVIDIA Corp. APX"
PRIORITY = "usb,nvme,emmc,sd,ufs"
NODE_PROP = "data"


@dataclass
class Call:
    kind: str
    argv: list
    cwd: object
    env: object

    @property
    def tool(self) -> str:
        return Path(self.argv[0]).name


@dataclass
class FakeRunner:
    lsusb: list = field(default_factory=lambda: [[APX]])
    adb_rc: int = 0
    boardctl_rc: int = 0
    flash_rc: int = 0
    calls: list = field(default_factory=list)
    props: dict = field(default_factory=dict)
    wrapper_text: str | None = None
    bare_lsusb: int = 0

    def tools(self) -> list:
        return [c.tool for c in self.calls]

    def named(self, tool: str) -> list:
        return [c for c in self.calls if c.tool == tool]

    def capture(self, argv, *, cwd=None, env=None, discard_stderr=False, timeout=None):
        call = Call("capture", list(argv), cwd, env)
        self.calls.append(call)
        if call.tool == "adb":
            return self.adb_rc, ""
        if call.tool == "lsusb":
            wrapper = Path(env["PATH"].split(":")[0]) / "cpp"
            if self.wrapper_text is None and wrapper.is_file():
                self.wrapper_text = wrapper.read_text()
            out = self.lsusb[min(self.bare_lsusb, len(self.lsusb) - 1)]
            self.bare_lsusb += 1
            return 0, "".join(f"{line}\n" for line in out)
        if call.tool == "fdtget":
            return 0, self.props.get(argv[3], PRIORITY) + "\n"
        raise AssertionError(f"unexpected captured program {argv}")

    def run(self, argv, *, cwd=None, env=None):
        call = Call("run", list(argv), cwd, env)
        self.calls.append(call)
        if call.tool == "fdtput":
            self.props[argv[3]] = argv[-1]
            return 0
        if call.tool == "boardctl":
            return self.boardctl_rc
        if call.tool == "avocado-tegra-bootimg":
            return 0
        if call.tool == "initrd-flash":
            return self.flash_rc
        raise AssertionError(f"unexpected program {argv}")


@dataclass
class Rig:
    environ: dict
    runner: FakeRunner
    stub_dir: Path
    work: Path
    kernel_image: Path | None
    sleeps: list = field(default_factory=list)

    def go(self, main_fn, capsys, argv=(), euid=0):
        rc = main_fn(list(argv), environ=self.environ, runner=self.runner, euid=euid, sleep=self.sleeps.append)
        captured = capsys.readouterr()
        return rc, captured.out, captured.err


def make_rig(tmp_path, *, profile="tegraflash", env=None, kernel=False, unpinned_ok=True, drop=(), runner=None, carrier=None, manifest="stone-jetson-orin-nano.json"):
    stub_dir = tmp_path / "stubs"
    write_stubs(stub_dir, tmp_path / "stub.log", tmp_path / "scenario.json")
    tree = build_tree(
        STONE_DIR / manifest, tmp_path / "tree", stub_dir, kernel=kernel, drop=drop, carrier=carrier
    )
    environ = {
        "AVOCADO_STONE_MANIFEST": str(tree.manifest),
        "AVOCADO_STONE_BUILD_DIR": str(tree.build_dir),
        "AVOCADO_STONE_DATA_DIR": str(tree.data_dir),
        "AVOCADO_PROVISION_PROFILE": profile,
        "AVOCADO_SDK_ARCH": "x86_64",
        "PATH": f"{stub_dir}:/usr/bin:/bin",
        "HOME": str(tmp_path / "home"),
        "AVOCADO_PROVISION_FORCE": "1",
    }
    if tree.kernel_image:
        environ["AVOCADO_PROVISION_KERNEL_IMAGE"] = str(tree.kernel_image)
    elif unpinned_ok:
        environ["AVOCADO_PROVISION_ALLOW_UNPINNED_KERNEL"] = "1"
    environ.update(env or {})
    return Rig(environ, runner or FakeRunner(), stub_dir, tree.build_dir / "tegraflash", tree.kernel_image)


@contextlib.contextmanager
def mutant_main(tmp_path, old, new):
    """Import a copy of the package whose cli.py has one exact edit; yield its main."""
    dest = tmp_path / "mutant" / "avocado_tegraflash"
    shutil.copytree(PACKAGE_DIR, dest, ignore=shutil.ignore_patterns("__pycache__"))
    cli = dest / "cli.py"
    source = cli.read_text()
    assert source.count(old) == 1, f"mutation anchor not unique: {source.count(old)}"
    cli.write_text(source.replace(old, new))
    saved = {k: v for k, v in sys.modules.items() if k == "avocado_tegraflash" or k.startswith("avocado_tegraflash.")}
    for name in saved:
        del sys.modules[name]
    sys.path.insert(0, str(dest.parent))
    try:
        yield importlib.import_module("avocado_tegraflash.cli").main
    finally:
        sys.path.remove(str(dest.parent))
        for name in [k for k in sys.modules if k == "avocado_tegraflash" or k.startswith("avocado_tegraflash.")]:
            del sys.modules[name]
        sys.modules.update(saved)


# Each predicate answers one falsifier; the mutation tests below show it can say False.


def nonroot_refused_cleanly(main_fn, rig, capsys) -> bool:
    rc, _, err = rig.go(main_fn, capsys, euid=1000)
    return rc == 1 and "root is required" in err and rig.runner.calls == [] and not rig.work.exists()


def prepare_only_touches_no_board(main_fn, rig, capsys) -> bool:
    rc, _, _ = rig.go(main_fn, capsys, argv=["--prepare-only"], euid=1000)
    forbidden = {"lsusb", "boardctl", "initrd-flash"}
    return rc == 0 and not forbidden & set(rig.runner.tools())


def second_board_stops_the_flash(main_fn, rig, capsys) -> bool:
    rc, _, _ = rig.go(main_fn, capsys)
    return rc == 1 and rig.runner.named("initrd-flash") == []


def failing_stage_stops_later_stages(main_fn, rig, capsys) -> bool:
    rc, _, _ = rig.go(main_fn, capsys)
    later = {"lsusb", "fdtget", "fdtput", "initrd-flash"}
    return rc == 1 and not later & set(rig.runner.tools())


# --- non-root and prepare-only (deviations root-check-first, prepare-only) ---


@pytest.mark.deviation("root-check-first")
def test_non_root_without_prepare_only_refuses_before_creating_anything(tmp_path, capsys):
    rig = make_rig(tmp_path)
    assert nonroot_refused_cleanly(main, rig, capsys)


@pytest.mark.deviation("root-check-first")
def test_non_root_refusal_prints_the_sudo_form_that_keeps_environment_and_path(tmp_path, capsys):
    rig = make_rig(tmp_path)
    _, _, err = rig.go(main, capsys, euid=1000)
    assert err == (
        "ERROR: root is required: the flash talks to the board over USB and the flash tool needs root.\n"
        "Run the same command again with sudo, keeping the environment and PATH:\n"
        '  sudo -E env PATH="$PATH" <the command you just ran>\n'
    )
    assert "python3 -m" not in err and "AVOCADO" not in err


@pytest.mark.deviation("root-check-first")
def test_non_root_refusal_comes_before_the_environment_is_read(capsys):
    rc = main([], environ={}, runner=FakeRunner(), euid=1000)
    err = capsys.readouterr().err
    assert (rc, "root is required" in err, "is not set" in err) == (1, True, False)


@pytest.mark.deviation("root-check-first")
def test_non_root_refusal_starts_no_program_and_keeps_the_build_dir_empty(tmp_path, capsys):
    rig = make_rig(tmp_path)
    rig.go(main, capsys, euid=1000)
    assert list(rig.work.parent.iterdir()) == []


@pytest.mark.deviation("root-check-first")
def test_root_check_failing_mutation_is_caught(tmp_path, capsys):
    rig = make_rig(tmp_path)
    old = "if not args.prepare_only and (os.geteuid() if euid is None else euid) != 0:"
    with mutant_main(tmp_path, old, "if False:") as mutated:
        assert nonroot_refused_cleanly(mutated, rig, capsys) is False


@pytest.mark.deviation("prepare-only")
def test_prepare_only_as_non_root_exits_0(tmp_path, capsys):
    rig = make_rig(tmp_path)
    rc, _, _ = rig.go(main, capsys, argv=["--prepare-only"], euid=1000)
    assert rc == 0


@pytest.mark.deviation("prepare-only")
def test_prepare_only_makes_no_board_contact(tmp_path, capsys):
    rig = make_rig(tmp_path, runner=FakeRunner(lsusb=[[APX, APX2]]))
    assert prepare_only_touches_no_board(main, rig, capsys)
    assert rig.sleeps == []


@pytest.mark.deviation("prepare-only")
def test_prepare_only_with_a_kernel_still_makes_no_board_contact(tmp_path, capsys):
    rig = make_rig(tmp_path, kernel=True)
    assert prepare_only_touches_no_board(main, rig, capsys)
    assert rig.runner.named("avocado-tegra-bootimg") != []


@pytest.mark.deviation("prepare-only")
def test_prepare_only_ends_with_the_work_directory_and_the_command(tmp_path, capsys):
    rig = make_rig(tmp_path)
    _, out, _ = rig.go(main, capsys, argv=["--prepare-only"], euid=1000)
    assert out.splitlines()[-2:] == [f"Work directory: {rig.work}", "Command: ./initrd-flash --erase-nvme"]


@pytest.mark.deviation("prepare-only")
def test_prepare_only_still_prepares_boot_priority_and_blanks_the_layout(tmp_path, capsys):
    rig = make_rig(tmp_path)
    rig.go(main, capsys, argv=["--prepare-only"], euid=1000)
    layout = (rig.work / "external-flash.xml.in").read_text()
    assert (rig.runner.props[str(rig.work / "L4TConfiguration.dtbo")], "APPUUID" in layout) == (
        "nvme,usb,emmc,sd,ufs",
        False,
    )


@pytest.mark.deviation("prepare-only")
def test_prepare_only_with_no_erase_flags_prints_the_bare_command(tmp_path, capsys):
    rig = make_rig(tmp_path, profile="tegraflash-mmc")
    _, out, _ = rig.go(main, capsys, argv=["--prepare-only"], euid=1000)
    assert out.splitlines()[-1] == "Command: ./initrd-flash"


@pytest.mark.deviation("prepare-only")
def test_prepare_only_calling_the_board_mutation_is_caught(tmp_path, capsys):
    rig = make_rig(tmp_path)
    contact = "    board = recovery.wait_for_single_board(runner, flash_env, boardctl_target='', boardctl_serial='', sleep=sleep, expected_ids=man.rcm_ids)\n"
    with mutant_main(tmp_path, "    if args.prepare_only:\n", contact + "    if False:\n") as mutated:
        assert prepare_only_touches_no_board(mutated, rig, capsys) is False


# --- refusals ---


def test_unknown_profile_names_the_five_accepted_profiles_and_creates_nothing(tmp_path, capsys):
    rig = make_rig(tmp_path, profile="tegraflash-ufs")
    rc, _, err = rig.go(main, capsys)
    accepted = ("tegraflash", "tegraflash-nvme", "tegraflash-mmc", "tegraflash-emmc", "tegraflash-sd")
    lines = [ln for ln in err.splitlines() if ln.startswith("ERROR:")]
    assert (rc, len(lines) == 1, all(p in lines[0] for p in accepted)) == (1, True, True)


def test_unknown_profile_starts_no_program_and_creates_no_work_dir(tmp_path, capsys):
    rig = make_rig(tmp_path, profile="tegraflash-ufs")
    rig.go(main, capsys)
    assert (rig.runner.calls, rig.work.exists()) == ([], False)


def test_missing_required_variable_exits_1_naming_it(tmp_path, capsys):
    rig = make_rig(tmp_path)
    del rig.environ["AVOCADO_STONE_DATA_DIR"]
    rc, _, err = rig.go(main, capsys)
    assert (rc, err) == (1, "ERROR: AVOCADO_STONE_DATA_DIR is not set\n")


def test_missing_bsp_directory_exits_1_naming_it_and_keeps_the_work_dir(tmp_path, capsys):
    rig = make_rig(tmp_path, drop=("tegraflash_bsp",))
    rc, _, err = rig.go(main, capsys)
    missing = Path(rig.environ["AVOCADO_STONE_DATA_DIR"]) / "tegraflash-bsp"
    assert (rc, f"BSP directory not found: {missing}" in err, rig.work.is_dir()) == (1, True, True)


def test_missing_bsp_directory_stops_every_later_stage(tmp_path, capsys):
    rig = make_rig(tmp_path, drop=("tegraflash_bsp",))
    assert failing_stage_stops_later_stages(main, rig, capsys)


def test_swallowing_a_stage_failure_mutation_is_caught(tmp_path, capsys):
    rig = make_rig(tmp_path, drop=("tegraflash_bsp",))
    old = "        staging.copy_bsp(cfg.data_dir, man.tegraflash_bsp, work)\n"
    new = (
        "        try:\n"
        "            staging.copy_bsp(cfg.data_dir, man.tegraflash_bsp, work)\n"
        "        except EngineError:\n"
        "            pass\n"
    )
    with mutant_main(tmp_path, old, new) as mutated:
        assert failing_stage_stops_later_stages(mutated, rig, capsys) is False


def test_cmdline_set_without_a_kernel_image_is_refused(tmp_path, capsys):
    rig = make_rig(tmp_path, env={"AVOCADO_KERNEL_CMDLINE": "quiet"})
    rc, _, err = rig.go(main, capsys)
    assert (rc, "no kernel Image was staged" in err) == (1, True)


# --- adb and call order ---


def test_failing_adb_still_exits_0_and_starts_the_daemon_twice_first(tmp_path, capsys):
    rig = make_rig(tmp_path, runner=FakeRunner(adb_rc=1))
    rc, _, _ = rig.go(main, capsys)
    first = rig.runner.calls[:2]
    assert (rc, [(c.tool, c.argv[1:]) for c in first]) == (0, [("adb", ["start-server"])] * 2)


def test_adb_fallback_searches_only_tegraflash_tools_not_the_rest_of_the_data_dir(tmp_path, capsys):
    rig = make_rig(tmp_path)
    (rig.stub_dir / "adb").unlink()
    rig.environ["PATH"] = str(rig.stub_dir)
    data_dir = Path(rig.environ["AVOCADO_STONE_DATA_DIR"])
    decoys = [data_dir / "adb", data_dir / "carrier-bsp" / "adb"]
    wanted = data_dir / "tegraflash-tools" / "adb"
    for path in [*decoys, wanted]:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("x")
    rc, _, _ = rig.go(main, capsys)
    adb_argv0 = [c.argv[0] for c in rig.runner.named("adb")]
    assert (rc, adb_argv0) == (0, [str(wanted)] * 2)


def test_kernel_run_calls_the_programs_in_the_oracles_order(tmp_path, capsys):
    rig = make_rig(tmp_path, kernel=True)
    rig.go(main, capsys)
    assert rig.runner.tools() == [
        "adb",
        "adb",
        "avocado-tegra-bootimg",
        "lsusb",
        "fdtget",
        "fdtput",
        "fdtget",
        "lsusb",
        "initrd-flash",
    ]


# --- recovery and the flash ---


def test_one_board_in_recovery_flashes_once_without_waiting(tmp_path, capsys):
    rig = make_rig(tmp_path)
    rc, _, _ = rig.go(main, capsys)
    flashes = rig.runner.named("initrd-flash")
    assert (rc, [c.argv for c in flashes], rig.sleeps) == (0, [["./initrd-flash", "--erase-nvme"]], [])


def test_flash_runs_in_the_work_directory(tmp_path, capsys):
    rig = make_rig(tmp_path)
    rig.go(main, capsys)
    assert rig.runner.named("initrd-flash")[0].cwd == rig.work


def test_flash_tool_status_becomes_the_exit_status(tmp_path, capsys):
    rig = make_rig(tmp_path, runner=FakeRunner(flash_rc=7))
    rc, _, _ = rig.go(main, capsys)
    assert rc == 7


@pytest.mark.deviation("one-board-only")
def test_two_boards_in_recovery_exit_1_listing_both_before_any_action(tmp_path, capsys):
    rig = make_rig(tmp_path, runner=FakeRunner(lsusb=[[APX, APX2]]))
    rc, _, err = rig.go(main, capsys)
    assert (rc, "Device 005" in err, "Device 006" in err) == (1, True, True)
    assert not {"boardctl", "initrd-flash"} & set(rig.runner.tools())


@pytest.mark.deviation("one-board-only")
def test_second_board_after_the_wait_stops_the_flash(tmp_path, capsys):
    rig = make_rig(tmp_path, runner=FakeRunner(lsusb=[[APX], [APX, APX2]]))
    assert second_board_stops_the_flash(main, rig, capsys)


@pytest.mark.deviation("one-board-only")
def test_second_board_after_the_wait_message_names_both(tmp_path, capsys):
    rig = make_rig(tmp_path, runner=FakeRunner(lsusb=[[APX], [APX, APX2]]))
    _, _, err = rig.go(main, capsys)
    assert "2 boards are in recovery mode" in err


@pytest.mark.deviation("one-board-only")
def test_skipping_the_recheck_mutation_is_caught(tmp_path, capsys):
    rig = make_rig(tmp_path, runner=FakeRunner(lsusb=[[APX], [APX, APX2]]))
    with mutant_main(tmp_path, "    recovery.recheck_single_board(runner, flash_env, board, expected_ids=man.rcm_ids)\n", "    pass\n") as mutated:
        assert second_board_stops_the_flash(mutated, rig, capsys) is False


def swapped_board_stops_the_flash(main_fn, rig, capsys) -> bool:
    rc, _, err = rig.go(main_fn, capsys)
    return rc == 1 and "changed" in err and rig.runner.named("initrd-flash") == []


@pytest.mark.deviation("one-board-only")
def test_a_different_single_board_after_the_wait_stops_the_flash(tmp_path, capsys):
    rig = make_rig(tmp_path, runner=FakeRunner(lsusb=[[APX], [APX2]]))
    assert swapped_board_stops_the_flash(main, rig, capsys)


@pytest.mark.deviation("one-board-only")
def test_the_same_single_board_after_the_wait_still_flashes(tmp_path, capsys):
    rig = make_rig(tmp_path, runner=FakeRunner(lsusb=[[APX], [APX]]))
    rc, _, _ = rig.go(main, capsys)
    assert (rc, len(rig.runner.named("initrd-flash"))) == (0, 1)


@pytest.mark.deviation("one-board-only")
def test_forgetting_the_waited_board_mutation_is_caught(tmp_path, capsys):
    rig = make_rig(tmp_path, runner=FakeRunner(lsusb=[[APX], [APX2]]))
    accept_any = "    recovery.recheck_single_board(runner, flash_env, recovery._recovery_boards(runner, flash_env)[0], expected_ids=man.rcm_ids)\n"
    with mutant_main(tmp_path, "    recovery.recheck_single_board(runner, flash_env, board, expected_ids=man.rcm_ids)\n", accept_any) as mutated:
        assert swapped_board_stops_the_flash(mutated, rig, capsys) is False


OTHER_ID_APX = "Bus 001 Device 005: ID 0955:7023 NVIDIA Corp. APX"


@pytest.mark.deviation("recovery-id-pinned")
def test_a_recovery_device_outside_the_manifest_ids_is_refused_before_the_flash(tmp_path, capsys):
    rig = make_rig(tmp_path, runner=FakeRunner(lsusb=[[OTHER_ID_APX]]))
    rc, _, err = rig.go(main, capsys)
    assert (rc, "0955:7023" in err, "0955:7523" in err, rig.runner.named("initrd-flash")) == (1, True, True, [])


@pytest.mark.deviation("recovery-id-pinned")
def test_the_recheck_is_given_the_manifest_ids(tmp_path, capsys, monkeypatch):
    from avocado_tegraflash import recovery

    seen = []
    real = recovery.recheck_single_board

    def spy(runner, env, expected, **kwargs):
        seen.append(kwargs)
        return real(runner, env, expected, **kwargs)

    monkeypatch.setattr(recovery, "recheck_single_board", spy)
    rig = make_rig(tmp_path)
    rc, _, _ = rig.go(main, capsys)
    assert (rc, seen) == (0, [{"expected_ids": ("0955:7523",)}])


@pytest.mark.deviation("recovery-id-pinned")
def test_the_wait_is_given_the_manifest_ids_and_does_not_warn_about_identity(tmp_path, capsys, monkeypatch):
    from avocado_tegraflash import recovery

    seen = []
    real = recovery.wait_for_single_board

    def spy(*args, **kwargs):
        seen.append(kwargs.get("expected_ids"))
        return real(*args, **kwargs)

    monkeypatch.setattr(recovery, "wait_for_single_board", spy)
    rig = make_rig(tmp_path)
    rc, out, _ = rig.go(main, capsys)
    assert (rc, seen, "not identity-checked" in out) == (0, [("0955:7523",)], False)


@pytest.mark.deviation("recovery-id-pinned")
def test_a_manifest_without_ids_flashes_one_device_after_a_warning(tmp_path, capsys):
    rig = make_rig(
        tmp_path, runner=FakeRunner(lsusb=[[OTHER_ID_APX]]), manifest="stone-jetson-agx-orin.json"
    )
    rc, out, _ = rig.go(main, capsys)
    assert (rc, "not identity-checked" in out, len(rig.runner.named("initrd-flash"))) == (0, True, 1)


# --- an OS error from a stage ends in one ERROR line, not a traceback ---


def test_os_error_from_a_stage_exits_1_with_an_error_line_and_stops_later_stages(tmp_path, capsys, monkeypatch):
    from avocado_tegraflash import staging

    def boom(*_a, **_k):
        raise OSError("No space left on device")

    monkeypatch.setattr(staging, "copy_bsp", boom)
    rig = make_rig(tmp_path)
    rc, _, err = rig.go(main, capsys)
    later = {"lsusb", "fdtget", "fdtput", "initrd-flash"}
    assert (rc, err, not later & set(rig.runner.tools())) == (1, "ERROR: No space left on device\n", True)


def test_keyboard_interrupt_from_a_stage_still_propagates(tmp_path, capsys, monkeypatch):
    from avocado_tegraflash import staging

    def interrupted(*_a, **_k):
        raise KeyboardInterrupt

    monkeypatch.setattr(staging, "copy_bsp", interrupted)
    rig = make_rig(tmp_path)
    with pytest.raises(KeyboardInterrupt):
        rig.go(main, capsys)


def test_not_catching_os_error_mutation_is_caught(tmp_path, capsys, monkeypatch):
    def boom(*_a, **_k):
        raise OSError("disk full")

    rig = make_rig(tmp_path)
    with mutant_main(tmp_path, "    except (EngineError, OSError) as exc:\n", "    except EngineError as exc:\n") as mutated:
        # The mutant imported its own copy of the package; patch that copy.
        monkeypatch.setattr(importlib.import_module("avocado_tegraflash.staging"), "copy_bsp", boom)
        with pytest.raises(OSError):
            rig.go(mutated, capsys)


@pytest.mark.deviation("boardctl-single-arguments")
def test_boardctl_target_with_shell_text_is_one_argument(tmp_path, capsys):
    rig = make_rig(tmp_path, env={"BOARDCTL_TARGET": "x; touch PWNED"}, runner=FakeRunner(lsusb=[[], [APX]]))
    rc, _, _ = rig.go(main, capsys)
    assert (rc, [c.argv for c in rig.runner.named("boardctl")]) == (0, [["boardctl", "-t", "x; touch PWNED", "recovery"]])


@pytest.mark.deviation("boardctl-single-arguments")
def test_boardctl_serial_follows_the_target_in_the_oracles_order(tmp_path, capsys):
    env = {"BOARDCTL_TARGET": "topo", "BOARDCTL_SERIAL": "S 1"}
    rig = make_rig(tmp_path, env=env, runner=FakeRunner(lsusb=[[], [APX]]))
    rig.go(main, capsys)
    assert rig.runner.named("boardctl")[0].argv == ["boardctl", "-t", "topo", "-s", "S 1", "recovery"]


def test_without_a_boardctl_target_the_wait_polls_without_boardctl(tmp_path, capsys):
    # Listings: the initial check, a first poll (empty, so one sleep), a second poll.
    rig = make_rig(tmp_path, runner=FakeRunner(lsusb=[[], [], [APX]]))
    rc, _, _ = rig.go(main, capsys)
    assert (rc, rig.runner.named("boardctl"), rig.sleeps) == (0, [], [1])


# --- cpp wrapper and flash environment ---


def wrapper_dir_of(runner) -> Path:
    return Path(runner.named("lsusb")[0].env["PATH"].split(":")[0])


@pytest.mark.deviation("absolute-cpp-wrapper")
def test_cpp_wrapper_execs_the_absolute_preprocessor(tmp_path, capsys):
    rig = make_rig(tmp_path)
    rig.go(main, capsys)
    assert rig.runner.wrapper_text == f'#!/bin/bash\nexec {rig.stub_dir}/x86_64-avocadosdk-linux-cpp "$@"\n'


def test_wrapper_directory_is_gone_after_success(tmp_path, capsys):
    rig = make_rig(tmp_path)
    rig.go(main, capsys)
    assert not wrapper_dir_of(rig.runner).exists()


def test_wrapper_directory_is_gone_after_an_engine_error(tmp_path, capsys):
    rig = make_rig(tmp_path, runner=FakeRunner(lsusb=[[APX, APX2]]))
    rc, _, _ = rig.go(main, capsys)
    assert (rc, wrapper_dir_of(rig.runner).exists()) == (1, False)


def test_flash_path_puts_the_wrapper_then_the_work_dir_before_the_callers_path(tmp_path, capsys):
    rig = make_rig(tmp_path)
    rig.go(main, capsys)
    env = rig.runner.named("initrd-flash")[0].env
    assert env["PATH"] == f"{wrapper_dir_of(rig.runner)}:{rig.work}:{rig.environ['PATH']}"


def test_flash_pythonwarnings_defaults_to_ignoring_syntax_warnings(tmp_path, capsys):
    rig = make_rig(tmp_path)
    rig.go(main, capsys)
    assert rig.runner.named("initrd-flash")[0].env["PYTHONWARNINGS"] == "ignore::SyntaxWarning"


def test_flash_pythonwarnings_keeps_the_callers_value(tmp_path, capsys):
    rig = make_rig(tmp_path, env={"PYTHONWARNINGS": "error"})
    rig.go(main, capsys)
    assert rig.runner.named("initrd-flash")[0].env["PYTHONWARNINGS"] == "error"


def test_without_a_kernel_image_the_flash_env_carries_no_cmdline_extra(tmp_path, capsys):
    rig = make_rig(tmp_path)
    rig.go(main, capsys)
    assert "AVOCADO_KERNEL_CMDLINE_EXTRA" not in rig.runner.named("initrd-flash")[0].env


# --- kernel image and PARTUUID pins ---


PIN = re.compile(r"avocado\.root_partuuid=([0-9A-F-]+) avocado\.root_partuuid_b=([0-9A-F-]+)$")


def pins_of(extra: str) -> tuple:
    match = PIN.search(extra)
    assert match, extra
    return match.groups()


def test_kernel_run_writes_the_command_line_pins_into_the_layout(tmp_path, capsys):
    rig = make_rig(tmp_path, kernel=True)
    rig.go(main, capsys)
    slot_a, slot_b = pins_of(rig.runner.named("initrd-flash")[0].env["AVOCADO_KERNEL_CMDLINE_EXTRA"])
    layout = (rig.work / "external-flash.xml.in").read_text()
    assert (f"<unique_guid>{slot_a}</unique_guid>" in layout, f"<unique_guid>{slot_b}</unique_guid>" in layout, "APPUUID" in layout) == (
        True,
        True,
        False,
    )


def test_kernel_run_gives_the_repack_the_same_command_line_extra_as_the_flash(tmp_path, capsys):
    rig = make_rig(tmp_path, kernel=True)
    rig.go(main, capsys)
    repack = rig.runner.named("avocado-tegra-bootimg")[0]
    assert repack.env["AVOCADO_KERNEL_CMDLINE_EXTRA"] == rig.runner.named("initrd-flash")[0].env["AVOCADO_KERNEL_CMDLINE_EXTRA"]


def test_kernel_run_repacks_boot_img_from_the_staged_kernel_and_initramfs(tmp_path, capsys):
    rig = make_rig(tmp_path, kernel=True)
    rig.go(main, capsys)
    argv = rig.runner.named("avocado-tegra-bootimg")[0].argv
    initramfs = rig.work / "avocado-image-initramfs-jetson-orin-nano.cpio.zst"
    assert (argv[2], argv[3], argv[4], argv[5]) == (f"{rig.work}/boot.img", str(rig.kernel_image), str(initramfs), f"{rig.work}/boot.img")


def test_existing_cmdline_extra_comes_first_then_the_pins(tmp_path, capsys):
    rig = make_rig(tmp_path, kernel=True, env={"AVOCADO_KERNEL_CMDLINE_EXTRA": "console=ttyS0"})
    rig.go(main, capsys)
    extra = rig.runner.named("initrd-flash")[0].env["AVOCADO_KERNEL_CMDLINE_EXTRA"]
    assert extra.startswith("console=ttyS0 avocado.root_partuuid=")


def test_kernel_image_that_does_not_exist_is_refused_before_any_board_contact(tmp_path, capsys):
    rig = make_rig(tmp_path, env={"AVOCADO_PROVISION_KERNEL_IMAGE": str(tmp_path / "absent")})
    rc, _, err = rig.go(main, capsys)
    assert (rc, "not found" in err, "lsusb" in rig.runner.tools()) == (1, True, False)


def test_without_a_kernel_image_the_prebuilt_warning_is_printed_and_the_layout_blanked(tmp_path, capsys):
    rig = make_rig(tmp_path)
    _, out, _ = rig.go(main, capsys)
    layout = (rig.work / "external-flash.xml.in").read_text()
    assert ("using prebuilt boot.img from BSP" in out, "APPUUID" in layout, rig.runner.named("avocado-tegra-bootimg")) == (
        True,
        False,
        [],
    )


# --- erase flags and media ---


def test_erase_only_adds_its_flag_after_the_nvme_default(tmp_path, capsys):
    rig = make_rig(tmp_path, env={"ERASE_ONLY": "1"})
    rig.go(main, capsys)
    assert rig.runner.named("initrd-flash")[0].argv == ["./initrd-flash", "--erase-nvme", "--erase-only"]


def test_emmc_profile_without_erase_variables_passes_no_flags(tmp_path, capsys):
    rig = make_rig(tmp_path, profile="tegraflash-emmc")
    rig.go(main, capsys)
    assert rig.runner.named("initrd-flash")[0].argv == ["./initrd-flash"]


def test_sd_device_from_the_environment_wins_over_the_manifest(tmp_path, capsys):
    rig = make_rig(tmp_path, profile="tegraflash-sd", env={"AVOCADO_PROVISION_SD_DEVICE": "mmcblk1"})
    rig.go(main, capsys)
    assert 'BOOTDEV="mmcblk1p1"' in (rig.work / ".env.initrd-flash").read_text()


def test_sd_device_defaults_to_the_manifests(tmp_path, capsys):
    rig = make_rig(tmp_path, profile="tegraflash-sd")
    rig.go(main, capsys)
    assert 'BOOTDEV="mmcblk0p1"' in (rig.work / ".env.initrd-flash").read_text()


# --- the provision log names the engine ---


def test_engine_line_follows_the_banner_and_names_the_package_directory(tmp_path, capsys):
    rig = make_rig(tmp_path)
    _, out, _ = rig.go(main, capsys)
    lines = out.splitlines()
    banner = lines.index("=== Tegraflash Provisioning Script ===")
    assert lines[banner + 1] == f"Engine: avocado_tegraflash from {PACKAGE_DIR}"


def test_dropping_the_engine_line_mutation_is_caught(tmp_path, capsys):
    rig = make_rig(tmp_path)
    old = '    print(f"Engine: {__package__} from {Path(__file__).resolve().parent}")\n'
    with mutant_main(tmp_path, old, "") as mutated:
        _, out, _ = rig.go(mutated, capsys)
    assert not any(line.startswith("Engine: ") for line in out.splitlines())


# --- validation still applies under --prepare-only ---


def test_prepare_only_refuses_a_malformed_sd_device_with_the_same_error_as_a_real_run(tmp_path, capsys):
    env = {"AVOCADO_PROVISION_SD_DEVICE": "mmcblk0;touch PWNED"}
    full = make_rig(tmp_path / "full", profile="tegraflash-sd", env=env)
    prepare = make_rig(tmp_path / "prepare", profile="tegraflash-sd", env=env)
    rc_full, _, err_full = full.go(main, capsys)
    rc_prepare, _, err_prepare = prepare.go(main, capsys, argv=["--prepare-only"], euid=1000)
    assert (rc_prepare, err_prepare) == (rc_full, err_full)
    assert (rc_prepare, err_prepare.startswith("ERROR: SD card device")) == (1, True)


def test_prepare_only_skipping_the_boot_device_validation_mutation_is_caught(tmp_path, capsys):
    env = {"AVOCADO_PROVISION_SD_DEVICE": "mmcblk0;touch PWNED"}
    rig = make_rig(tmp_path, profile="tegraflash-sd", env=env)
    old = (
        "    device = settings.apply_boot_device(\n"
        "        work, media, sd_device=cfg.sd_device or man.sd_device, nvme_pci=cfg.nvme_pci\n"
        "    )\n"
    )
    # The stand-in applies the nvme profile instead, so only the SD validation is skipped.
    with mutant_main(tmp_path, old, '    device = settings.apply_boot_device(work, settings.Media.NVME, sd_device="")\n') as mutated:
        rc, _, _ = rig.go(mutated, capsys, argv=["--prepare-only"], euid=1000)
    assert rc == 0


@pytest.mark.deviation("prepare-only")
def test_prepare_only_leaves_the_rewritten_env_file_for_the_sd_profile(tmp_path, capsys):
    rig = make_rig(tmp_path, profile="tegraflash-sd", env={"AVOCADO_PROVISION_SD_DEVICE": "mmcblk1"})
    rc, _, _ = rig.go(main, capsys, argv=["--prepare-only"], euid=1000)
    lines = (rig.work / ".env.initrd-flash").read_text().splitlines()
    assert rc == 0
    assert lines[:3] == ['BOOTDEV="mmcblk1p1"', 'ROOTFS_DEVICE="mmcblk1"', "EXTERNAL_ROOTFS_DRIVE=1"]


# --- the profile is checked before the manifest is read ---


def test_unknown_profile_is_refused_before_the_manifest_is_read(tmp_path, capsys):
    rig = make_rig(tmp_path, profile="tegraflash-ufs", env={"AVOCADO_STONE_MANIFEST": str(tmp_path / "absent.json")})
    rc, out, err = rig.go(main, capsys)
    assert (rc, "tegraflash-sd" in err, "absent.json" in err) == (1, True, False)
    assert "Manifest:" not in out


def test_reading_the_manifest_before_the_profile_mutation_is_caught(tmp_path, capsys):
    rig = make_rig(tmp_path, profile="tegraflash-ufs", env={"AVOCADO_STONE_MANIFEST": str(tmp_path / "absent.json")})
    old = "    media = media_for_profile(cfg.profile)\n"
    with mutant_main(tmp_path, old, "    read_manifest(cfg.manifest)\n" + old) as mutated:
        _, _, err = rig.go(mutated, capsys)
    assert "absent.json" in err


# --- the build directory is locked (deviation build-dir-locked) ---

_HOLDER = (
    "import fcntl, pathlib, sys\n"
    "fh = open(sys.argv[1], 'a')\n"
    "fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)\n"
    "pathlib.Path(sys.argv[2]).write_text('held')\n"
    "sys.stdin.read()\n"
)


@contextlib.contextmanager
def lock_held_by_another_process(rig, tmp_path):
    """A real second process that holds the lock file until its stdin closes."""
    build = Path(rig.environ["AVOCADO_STONE_BUILD_DIR"])
    build.mkdir(parents=True, exist_ok=True)
    ready = tmp_path / "ready"
    log = tmp_path / "holder.log"
    with log.open("w") as out:
        holder = subprocess.Popen(
            [sys.executable, "-I", "-c", _HOLDER, str(build / "tegraflash.lock"), str(ready)],
            stdin=subprocess.PIPE, stdout=out, stderr=out, start_new_session=True,
        )
        try:
            for _ in range(200):
                if ready.exists():
                    break
                time.sleep(0.05)
            assert ready.exists(), log.read_text()
            yield holder
        finally:
            holder.stdin.close()
            holder.wait(timeout=10)


@pytest.mark.deviation("build-dir-locked")
@pytest.mark.parametrize("argv, euid", [([], 0), (["--prepare-only"], 1000)])
def test_a_second_run_on_a_locked_build_dir_is_refused_before_the_work_dir_is_touched(tmp_path, capsys, argv, euid):
    rig = make_rig(tmp_path)
    stale = rig.work / "stale.txt"
    stale.parent.mkdir(parents=True)
    stale.write_text("run A's tree")
    with lock_held_by_another_process(rig, tmp_path):
        rc, _, err = rig.go(main, capsys, argv=argv, euid=euid)
    assert rc == 1 and "another provisioning run" in err and rig.environ["AVOCADO_STONE_BUILD_DIR"] in err
    assert stale.read_text() == "run A's tree" and rig.runner.named("initrd-flash") == []


@pytest.mark.deviation("build-dir-locked")
def test_the_lock_is_released_when_the_holding_process_exits(tmp_path, capsys):
    rig = make_rig(tmp_path)
    with lock_held_by_another_process(rig, tmp_path):
        assert rig.go(main, capsys, argv=["--prepare-only"], euid=1000)[0] == 1
    assert rig.go(main, capsys, argv=["--prepare-only"], euid=1000)[0] == 0


@pytest.mark.deviation("build-dir-locked")
def test_taking_no_lock_mutation_is_caught(tmp_path, capsys):
    rig = make_rig(tmp_path)
    with lock_held_by_another_process(rig, tmp_path):
        with mutant_main(tmp_path, "    with _build_dir_lock(cfg.build_dir):\n", "    with open(os.devnull):\n") as mutated:
            rc, _, _ = rig.go(mutated, capsys, argv=["--prepare-only"], euid=1000)
    assert rc == 0


# --- partition fit (deviation partition-fit-refused) ---


def _grow_rootfs(rig, size):
    (found,) = Path(rig.environ["AVOCADO_STONE_DATA_DIR"]).rglob("avocado-image-rootfs-jetson-orin-nano.erofs-lz4")
    found.write_bytes(b"\0" * size)


@pytest.mark.deviation("partition-fit-refused")
def test_oversize_rootfs_is_refused_naming_image_and_partition_before_any_flash(tmp_path, capsys):
    rig = make_rig(tmp_path)
    _grow_rootfs(rig, 8193)
    rc, _, err = rig.go(main, capsys)
    assert rc == 1
    assert "avocado-image-rootfs-jetson-orin-nano.erofs-lz4" in err and "APP" in err and "8193" in err
    assert rig.runner.named("initrd-flash") == []


@pytest.mark.deviation("partition-fit-refused")
def test_exact_fit_rootfs_still_flashes(tmp_path, capsys):
    rig = make_rig(tmp_path)
    _grow_rootfs(rig, 8192)
    rc, _, _ = rig.go(main, capsys)
    assert rc == 0 and len(rig.runner.named("initrd-flash")) == 1


@pytest.mark.deviation("partition-fit-refused")
def test_prepare_only_refuses_an_oversize_image(tmp_path, capsys):
    rig = make_rig(tmp_path)
    _grow_rootfs(rig, 8193)
    rc, _, err = rig.go(main, capsys, argv=["--prepare-only"], euid=1000)
    assert rc == 1 and "does not fit partition APP" in err


@pytest.mark.deviation("partition-fit-refused")
def test_the_emmc_profile_is_fit_checked_against_the_emmc_layout(tmp_path, capsys):
    # 7000 fits the external APP (8192) but not the eMMC APP (6144): only a check
    # that reads the layout after the eMMC swap refuses it.
    rig = make_rig(tmp_path, profile="tegraflash-emmc")
    _grow_rootfs(rig, 7000)
    rc, _, err = rig.go(main, capsys)
    assert (rc, "does not fit partition APP (6144 bytes)" in err, rig.runner.named("initrd-flash")) == (1, True, [])


# --- operator confirmation before the erase (deviation device-confirmation) ---


def _terminal(monkeypatch, answer=None):
    """Give main a terminal on stdin; return the list of prompts it was shown."""
    prompts = []

    def fake_input(prompt=""):
        prompts.append(prompt)
        return answer(prompt) if callable(answer) else answer

    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr("builtins.input", fake_input)
    return prompts


@pytest.mark.deviation("device-confirmation")
def test_a_wrong_retype_refuses_before_the_flash(tmp_path, capsys, monkeypatch):
    prompts = _terminal(monkeypatch, "9:9")
    rig = make_rig(tmp_path, env={"AVOCADO_PROVISION_FORCE": "0"})
    rc, _, err = rig.go(main, capsys)
    assert (rc, len(prompts), "device confirmation failed" in err, rig.runner.named("initrd-flash")) == (1, 1, True, [])


@pytest.mark.deviation("device-confirmation")
def test_the_confirmation_precedes_the_recheck_and_names_the_same_board(tmp_path, capsys, monkeypatch):
    from avocado_tegraflash import confirm, recovery

    order = []
    real_confirm, real_recheck = confirm.confirm_device, recovery.recheck_single_board

    def confirm_spy(board, media, **kwargs):
        order.append(("confirm", board.bus, board.device))
        return real_confirm(board, media, **kwargs)

    def recheck_spy(runner, env, expected, **kwargs):
        order.append(("recheck", expected.bus, expected.device))
        return real_recheck(runner, env, expected, **kwargs)

    monkeypatch.setattr(confirm, "confirm_device", confirm_spy)
    monkeypatch.setattr(recovery, "recheck_single_board", recheck_spy)
    rig = make_rig(tmp_path)
    rc, _, _ = rig.go(main, capsys)
    assert rc == 0
    assert [o[0] for o in order] == ["confirm", "recheck"] and order[0][1:] == order[1][1:]


@pytest.mark.deviation("device-confirmation")
def test_a_correct_retype_flashes(tmp_path, capsys, monkeypatch):
    prompts = _terminal(monkeypatch, lambda p: re.search(r"\(USB (\S+)\)", p).group(1))
    rig = make_rig(tmp_path, env={"AVOCADO_PROVISION_FORCE": "0"})
    rc, _, _ = rig.go(main, capsys)
    assert (rc, len(prompts), len(rig.runner.named("initrd-flash"))) == (0, 1, 1)


@pytest.mark.deviation("device-confirmation")
def test_force_one_flashes_without_a_prompt(tmp_path, capsys, monkeypatch):
    prompts = _terminal(monkeypatch, "wrong")
    rig = make_rig(tmp_path)
    rc, _, _ = rig.go(main, capsys)
    assert (rc, prompts, len(rig.runner.named("initrd-flash"))) == (0, [], 1)


@pytest.mark.deviation("device-confirmation")
def test_prepare_only_never_prompts_even_with_force_zero(tmp_path, capsys, monkeypatch):
    prompts = _terminal(monkeypatch, "wrong")
    rig = make_rig(tmp_path, env={"AVOCADO_PROVISION_FORCE": "0"})
    rc, _, _ = rig.go(main, capsys, argv=["--prepare-only"], euid=1000)
    assert (rc, prompts, rig.runner.named("initrd-flash")) == (0, [], [])


@pytest.mark.deviation("device-confirmation")
def test_force_zero_without_a_terminal_refuses(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    rig = make_rig(tmp_path, env={"AVOCADO_PROVISION_FORCE": "0"})
    rc, _, err = rig.go(main, capsys)
    assert (rc, "no terminal" in err, rig.runner.named("initrd-flash")) == (1, True, [])


@pytest.mark.deviation("required-image-refused")
@pytest.mark.parametrize("key", ["rootfs", "var", "tegraflash_esp"])
def test_a_manifest_without_a_required_image_key_is_refused_before_any_staging_or_board_contact(
    tmp_path, capsys, key
):
    import json

    rig = make_rig(tmp_path)
    path = Path(rig.environ["AVOCADO_STONE_MANIFEST"])
    doc = json.loads(path.read_text())
    del doc["storage_devices"]["rootdisk"]["images"][key]
    path.write_text(json.dumps(doc))
    rc, _, err = rig.go(main, capsys)
    assert (rc, f"images.{key}" in err) == (1, True)
    assert {"lsusb", "initrd-flash"}.isdisjoint(rig.runner.tools())
    assert not rig.work.exists()


@pytest.mark.deviation("device-confirmation")
def test_the_prompt_names_every_medium_the_flags_erase(tmp_path, capsys, monkeypatch):
    prompts = _terminal(monkeypatch, lambda p: re.search(r"\(USB (\S+)\)", p).group(1))
    rig = make_rig(tmp_path, profile="tegraflash-sd", env={"AVOCADO_PROVISION_FORCE": "0", "ERASE_NVME": "1", "AVOCADO_PROVISION_SD_DEVICE": "mmcblk1"})
    rc, _, _ = rig.go(main, capsys)
    assert rc == 0 and "sd" in prompts[0] and "nvme" in prompts[0]


@pytest.mark.deviation("device-confirmation")
def test_force_unset_on_a_terminal_prompts_and_a_wrong_retype_refuses(tmp_path, capsys, monkeypatch):
    prompts = _terminal(monkeypatch, "9:9")
    rig = make_rig(tmp_path)
    del rig.environ["AVOCADO_PROVISION_FORCE"]
    rc, _, err = rig.go(main, capsys)
    assert (rc, len(prompts), "device confirmation failed" in err, rig.runner.named("initrd-flash")) == (1, 1, True, [])


@pytest.mark.deviation("device-confirmation")
def test_force_unset_without_a_terminal_logs_the_skip_and_proceeds(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    rig = make_rig(tmp_path)
    del rig.environ["AVOCADO_PROVISION_FORCE"]
    rc, out, _ = rig.go(main, capsys)
    assert (rc, "device confirmation skipped: no terminal" in out, len(rig.runner.named("initrd-flash"))) == (0, True, 1)


@pytest.mark.deviation("required-image-refused")
def test_an_unusable_required_image_is_refused_before_the_old_work_directory_is_deleted(tmp_path, capsys):
    import json

    rig = make_rig(tmp_path)
    rig.work.mkdir(parents=True)
    (rig.work / "keep.me").write_text("previous staging")
    data_dir = Path(rig.environ["AVOCADO_STONE_DATA_DIR"])
    name = json.loads(Path(rig.environ["AVOCADO_STONE_MANIFEST"]).read_text())["storage_devices"]["rootdisk"]["images"]["var"]
    (data_dir / name).unlink()
    rc, _, err = rig.go(main, capsys)
    assert (rc, "required image(s) unusable" in err, (rig.work / "keep.me").exists()) == (1, True, True)


# --- the staged env file, read as the flash reads it (plain-assignment rule) ---


def _bsp_env(rig):
    (found,) = [p for p in Path(rig.environ["AVOCADO_STONE_DATA_DIR"]).rglob(".env.initrd-flash")]
    return found


def _append_to_bsp_env(rig, text):
    env = _bsp_env(rig)
    env.write_text(env.read_text() + text)


@pytest.mark.deviation("partition-fit-refused")
@pytest.mark.parametrize("prepare", [False, True])
@pytest.mark.parametrize("line", ['export ROOTFS_IMAGE="big.img"', '  ROOTFS_DEVICE="sda"', "DATAFILE+=x"])
def test_a_non_plain_assignment_of_a_checked_key_is_refused_before_any_flash(tmp_path, capsys, line, prepare):
    rig = make_rig(tmp_path)
    _append_to_bsp_env(rig, line + "\n")
    rc, _, err = rig.go(main, capsys, argv=["--prepare-only"] if prepare else [], euid=1000 if prepare else 0)
    assert rc == 1 and "sources this file with bash" in err
    assert rig.runner.named("initrd-flash") == []


@pytest.mark.deviation("device-confirmation")
def test_a_staged_rootfs_device_that_is_not_the_profiles_is_refused_before_the_flash(tmp_path, capsys, monkeypatch):
    # A rewrite that no longer takes effect leaves the BSP's own value behind.
    monkeypatch.setattr("avocado_tegraflash.settings._rewrite", lambda *_a, **_k: None)
    rig = make_rig(tmp_path, profile="tegraflash-sd", env={"AVOCADO_PROVISION_SD_DEVICE": "mmcblk1"})
    rc, _, err = rig.go(main, capsys)
    assert rc == 1 and "ROOTFS_DEVICE" in err and "nvme0n1" in err and "mmcblk1" in err
    assert rig.runner.named("initrd-flash") == []


@pytest.mark.deviation("partition-fit-refused")
def test_a_datafile_other_than_the_staged_var_image_is_refused(tmp_path, capsys):
    rig = make_rig(tmp_path)
    _append_to_bsp_env(rig, 'DATAFILE="other.img"\n')
    rc, _, err = rig.go(main, capsys)
    assert rc == 1 and "DATAFILE" in err and "other.img" in err
    assert rig.runner.named("initrd-flash") == []


@pytest.mark.deviation("device-confirmation")
@pytest.mark.parametrize(
    "line,names_emmc",
    [("", True), ("NO_INTERNAL_STORAGE=0\n", True), ("NO_INTERNAL_STORAGE=1\n", False)],
)
def test_the_prompt_names_emmc_when_the_staged_env_makes_the_flash_erase_it(
    tmp_path, capsys, monkeypatch, line, names_emmc
):
    prompts = _terminal(monkeypatch, lambda p: re.search(r"\(USB (\S+)\)", p).group(1))
    rig = make_rig(tmp_path, env={"AVOCADO_PROVISION_FORCE": "0"})
    _append_to_bsp_env(rig, line)
    rc, _, _ = rig.go(main, capsys)
    assert rc == 0 and len(prompts) == 1
    assert ("emmc" in prompts[0].splitlines()[0]) is names_emmc


@pytest.mark.deviation("device-confirmation")
def test_an_external_rootfs_drive_the_engine_did_not_write_is_refused_before_the_flash(tmp_path, capsys):
    rig = make_rig(tmp_path)
    # The rewrite fixes every column-0 line, so only a file sourced afterwards can undo it.
    (_bsp_env(rig).parent / ".presigning-vars").write_text("EXTERNAL_ROOTFS_DRIVE=0\n")
    rc, _, err = rig.go(main, capsys)
    assert rc == 1 and "EXTERNAL_ROOTFS_DRIVE" in err
    assert rig.runner.named("initrd-flash") == []


@pytest.mark.deviation("device-confirmation")
@pytest.mark.parametrize(
    "profile,env,node",
    [
        ("tegraflash", {}, "nvme0n1"),
        ("tegraflash-sd", {"AVOCADO_PROVISION_SD_DEVICE": "mmcblk1"}, "mmcblk1"),
        ("tegraflash-emmc", {}, "mmcblk0"),
    ],
)
def test_the_prompt_names_the_device_node_the_flash_will_use(tmp_path, capsys, monkeypatch, profile, env, node):
    prompts = _terminal(monkeypatch, lambda p: re.search(r"\(USB (\S+)\)", p).group(1))
    rig = make_rig(tmp_path, profile=profile, env={"AVOCADO_PROVISION_FORCE": "0", **env})
    rc, _, _ = rig.go(main, capsys)
    assert rc == 0 and f"({node})" in prompts[0].splitlines()[0]
