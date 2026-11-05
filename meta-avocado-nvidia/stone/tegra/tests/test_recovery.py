"""Waiting for exactly one board in recovery mode."""

import pytest

from avocado_tegraflash import EngineError
from avocado_tegraflash.recovery import recheck_single_board, wait_for_single_board
from avocado_tegraflash.usb import UsbDevice

NONE = "Bus 001 Device 004: ID 0955:7020 NVIDIA Corp. Linux for Tegra\n"
ONE = NONE + "Bus 001 Device 005: ID 0955:7523 NVIDIA Corp. APX\n"
TWO = ONE + "Bus 003 Device 009: ID 0955:7523 NVIDIA Corp. APX\n"
BOARD = UsbDevice("001", "005", "0955", "7523", "NVIDIA Corp. APX")


class ScriptRunner:
    """lsusb outputs come from a script (the last one repeats); run() is recorded."""

    def __init__(self, listings, run_status=0):
        self.listings = list(listings)
        self.lsusb_calls = 0
        self.runs = []
        self.run_status = run_status

    def capture(self, argv, *, cwd=None, env=None, discard_stderr=False, timeout=None):
        assert list(argv) == ["lsusb", "-d", "0955:"]
        i = min(self.lsusb_calls, len(self.listings) - 1)
        self.lsusb_calls += 1
        return 0, self.listings[i]

    def run(self, argv, *, cwd=None, env=None):
        self.runs.append(list(argv))
        return self.run_status


@pytest.fixture
def env(tmp_path):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    tool = bindir / "boardctl"
    tool.write_text("#!/bin/sh\n")
    tool.chmod(0o755)
    return {"PATH": str(bindir)}


class Sleeper:
    def __init__(self):
        self.calls = []

    def __call__(self, seconds):
        self.calls.append(seconds)


def wait(runner, env, *, target="", serial="", sleeper=None, polls=60, logs=None):
    return wait_for_single_board(
        runner,
        env,
        boardctl_target=target,
        boardctl_serial=serial,
        sleep=sleeper or Sleeper(),
        polls=polls,
        log=(logs.append if logs is not None else (lambda _m: None)),
    )


def test_one_board_is_returned_without_boardctl_or_sleep():
    runner, sleeper, logs = ScriptRunner([ONE]), Sleeper(), []
    assert wait(runner, {}, target="x", sleeper=sleeper, logs=logs) == BOARD
    assert (runner.runs, sleeper.calls, logs) == ([], [], ["Device already in RCM mode"])


def test_device_mode_board_alone_is_not_a_recovery_board():
    runner = ScriptRunner([NONE])
    with pytest.raises(EngineError, match="did not enter RCM mode"):
        wait(runner, {}, polls=2)


@pytest.mark.deviation("one-board-only")
def test_two_boards_refuse_at_once_listing_each_and_running_nothing(env):
    runner, sleeper = ScriptRunner([TWO]), Sleeper()
    with pytest.raises(EngineError) as exc:
        wait(runner, env, target="x", sleeper=sleeper)
    text = str(exc.value)
    assert "Bus 001 Device 005" in text and "Bus 003 Device 009" in text
    assert (runner.runs, sleeper.calls, runner.lsusb_calls) == ([], [], 1)


def test_two_boards_appearing_while_waiting_refuse():
    runner = ScriptRunner([NONE, TWO])
    with pytest.raises(EngineError, match="Bus 003 Device 009"):
        wait(runner, {}, polls=5)


@pytest.mark.deviation("boardctl-single-arguments")
def test_target_with_shell_text_reaches_boardctl_as_one_argument(env):
    runner = ScriptRunner([NONE, ONE])
    wait(runner, env, target="x; touch PWNED")
    assert runner.runs == [["boardctl", "-t", "x; touch PWNED", "recovery"]]


@pytest.mark.deviation("boardctl-single-arguments")
def test_target_with_a_space_is_one_argument_and_serial_precedes_recovery(env):
    runner = ScriptRunner([NONE, ONE])
    wait(runner, env, target="a b", serial="S 1")
    assert runner.runs == [["boardctl", "-t", "a b", "-s", "S 1", "recovery"]]


def test_boardctl_success_waits_with_the_boardctl_message_then_returns(env):
    runner, logs = ScriptRunner([NONE, NONE, ONE]), []
    assert wait(runner, env, target="t", logs=logs) == BOARD
    assert logs[0] == "Device not in RCM mode, attempting recovery via boardctl (target=t)..."
    assert logs[1] == "Waiting for device to enter RCM mode..."
    assert logs[-1] == "Device in RCM mode"


def test_boardctl_failure_warns_and_falls_back_to_the_manual_prompt(env):
    runner, logs = ScriptRunner([NONE, ONE], run_status=3), []
    assert wait(runner, env, target="t", logs=logs) == BOARD
    assert "WARNING: boardctl failed (exit 3) - device may not be connected or TOPO not detected" in logs
    assert "Falling back to waiting for manual recovery..." in logs
    assert "Please put device into recovery mode (hold recovery button, press reset)..." in logs


def test_no_target_skips_boardctl_and_prompts(env):
    runner, logs = ScriptRunner([NONE, ONE]), []
    wait(runner, env, logs=logs)
    assert runner.runs == []
    assert "Please put device into recovery mode (hold recovery button, press reset)..." in logs


def test_target_without_boardctl_on_path_skips_it(tmp_path):
    runner = ScriptRunner([NONE, ONE])
    wait(runner, {"PATH": str(tmp_path)}, target="t")
    assert runner.runs == []


def test_empty_serial_adds_no_serial_argument(env):
    runner = ScriptRunner([NONE, ONE])
    wait(runner, env, target="t", serial="")
    assert runner.runs == [["boardctl", "-t", "t", "recovery"]]


def test_expiry_raises_with_the_poll_count_in_the_message_and_sleeps_each_poll():
    runner, sleeper = ScriptRunner([NONE]), Sleeper()
    with pytest.raises(EngineError) as exc:
        wait(runner, {}, sleeper=sleeper, polls=7)
    assert str(exc.value) == "Device did not enter RCM mode (waited 7s)"
    assert sleeper.calls == [1] * 7


def test_default_polls_is_sixty():
    runner = ScriptRunner([NONE])
    with pytest.raises(EngineError) as exc:
        wait_for_single_board(
            runner, {}, boardctl_target="", boardctl_serial="", sleep=lambda _s: None, log=lambda _m: None
        )
    assert str(exc.value) == "Device did not enter RCM mode (waited 60s)"


def test_board_appearing_on_the_last_poll_is_still_found():
    runner = ScriptRunner([NONE, NONE, NONE, ONE])
    assert wait(runner, {}, polls=3) == BOARD


def test_recheck_returns_the_single_board():
    assert recheck_single_board(ScriptRunner([ONE]), {}, BOARD) == BOARD


def test_recheck_refuses_when_a_second_board_is_present():
    with pytest.raises(EngineError, match="Bus 003 Device 009"):
        recheck_single_board(ScriptRunner([TWO]), {}, BOARD)


def test_recheck_refuses_when_the_board_vanished():
    with pytest.raises(EngineError, match="no board in recovery mode"):
        recheck_single_board(ScriptRunner([NONE]), {}, BOARD)


@pytest.mark.deviation("one-board-only")
@pytest.mark.parametrize(
    "other",
    [
        UsbDevice("002", "005", "0955", "7523", "NVIDIA Corp. APX"),
        UsbDevice("001", "006", "0955", "7523", "NVIDIA Corp. APX"),
        UsbDevice("001", "005", "0955", "7323", "NVIDIA Corp. APX"),
    ],
    ids=["bus", "device", "pid"],
)
def test_recheck_refuses_a_different_single_board(other):
    listing = f"Bus {other.bus} Device {other.device}: ID {other.vid}:{other.pid} {other.desc}\n"
    with pytest.raises(EngineError, match="board in recovery mode changed"):
        recheck_single_board(ScriptRunner([listing]), {}, BOARD)


@pytest.mark.deviation("one-board-only")
def test_recheck_ignores_a_changed_description_of_the_same_board():
    listing = "Bus 001 Device 005: ID 0955:7523 NVIDIA Corp. RCM\n"
    assert recheck_single_board(ScriptRunner([listing]), {}, BOARD).device == "005"


# ---- a failed lsusb is not an empty bus ----


class StatusRunner(ScriptRunner):
    """Like ScriptRunner, but each step is (status, listing)."""

    def capture(self, argv, *, cwd=None, env=None, discard_stderr=False, timeout=None):
        i = min(self.lsusb_calls, len(self.listings) - 1)
        self.lsusb_calls += 1
        return self.listings[i]


def test_missing_lsusb_while_waiting_reports_the_listing_failure_not_a_missing_board():
    runner = StatusRunner([(127, "")])
    with pytest.raises(EngineError, match=r"listing failed \(lsusb status 127\)") as exc:
        wait(runner, {}, polls=3)
    assert "did not enter RCM mode" not in str(exc.value)


def test_a_timed_out_lsusb_is_named_by_its_status():
    with pytest.raises(EngineError, match="lsusb status 124"):
        wait(StatusRunner([(124, "")]), {}, polls=2)


def test_an_empty_bus_still_reports_the_board_never_appeared():
    # lsusb -d exits 1 with no output when nothing matches: the normal no-board run.
    with pytest.raises(EngineError, match=r"did not enter RCM mode \(waited 2s\)"):
        wait(StatusRunner([(1, "")]), {}, polls=2)


def test_one_failed_listing_while_waiting_is_ridden_out_when_the_board_then_appears():
    runner = StatusRunner([(127, ""), (0, ONE)])
    assert wait(runner, {}, polls=5) == BOARD


def test_a_failure_followed_by_a_clean_empty_bus_reports_the_missing_board():
    runner = StatusRunner([(127, ""), (1, "")])
    with pytest.raises(EngineError, match="did not enter RCM mode"):
        wait(runner, {}, polls=3)


def test_recheck_reports_a_failed_listing_not_a_missing_board():
    with pytest.raises(EngineError, match="lsusb status 127"):
        recheck_single_board(StatusRunner([(127, "")]), {}, BOARD)


def test_missing_lsusb_raises_at_the_first_wait_poll_without_sleeping(env):
    runner, sleeper = StatusRunner([(127, "")]), Sleeper()
    with pytest.raises(EngineError, match="lsusb status 127"):
        wait(runner, env, target="t", sleeper=sleeper, polls=60)
    assert (sleeper.calls, runner.runs, runner.lsusb_calls) == ([], [["boardctl", "-t", "t", "recovery"]], 2)


def test_other_failure_statuses_still_ride_out_the_polls():
    sleeper = Sleeper()
    with pytest.raises(EngineError, match="lsusb status 124"):
        wait(StatusRunner([(124, "")]), {}, sleeper=sleeper, polls=3)
    assert sleeper.calls == [1, 1, 1]
