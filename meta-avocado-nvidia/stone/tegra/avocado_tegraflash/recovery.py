"""Find exactly one Jetson in recovery mode, asking boardctl or the user to put it there."""

import shutil
import time
from collections.abc import Callable, Mapping

from . import EngineError
from .runner import CANNOT_START, Runner
from .usb import ListingFailed, UsbDevice, is_recovery, list_nvidia


def _recovery_boards(runner: Runner, env: Mapping[str, str]) -> list[UsbDevice]:
    boards = [d for d in list_nvidia(runner, env) if is_recovery(d)]
    if len(boards) > 1:
        listing = ", ".join(f"Bus {d.bus} Device {d.device}" for d in boards)
        raise EngineError(
            f"{len(boards)} boards are in recovery mode ({listing}); "
            "connect exactly one so the wrong board cannot be flashed"
        )
    return boards


def _poll(runner: Runner, env: Mapping[str, str], failures: list[ListingFailed]) -> list[UsbDevice]:
    """One look at the bus; a failed listing is remembered and counts as no board for now."""
    try:
        return _recovery_boards(runner, env)
    except ListingFailed as exc:
        failures.append(exc)
        return []


def _identity(device: UsbDevice) -> tuple[str, str, str, str]:
    return device.bus, device.device, device.vid.lower(), device.pid.lower()


def recheck_single_board(runner: Runner, env: Mapping[str, str], expected: UsbDevice) -> UsbDevice:
    """The flash starts right after this: a second board, or a different one, must stop it."""
    boards = _recovery_boards(runner, env)
    if not boards:
        raise EngineError("no board in recovery mode")
    if _identity(boards[0]) != _identity(expected):
        raise EngineError(
            f"the board in recovery mode changed (was Bus {expected.bus} Device {expected.device}, "
            f"now Bus {boards[0].bus} Device {boards[0].device}); connect exactly one board and retry"
        )
    return boards[0]


def wait_for_single_board(
    runner: Runner,
    env: Mapping[str, str],
    *,
    boardctl_target: str,
    boardctl_serial: str,
    sleep: Callable[[float], None] = time.sleep,
    polls: int = 60,
    log: Callable[[str], None] = print,
) -> UsbDevice:
    failures: list[ListingFailed] = []
    boards = _poll(runner, env, failures)
    if boards:
        log("Device already in RCM mode")
        return boards[0]

    attempted = False
    if boardctl_target and shutil.which("boardctl", path=env.get("PATH", "")):
        log(f"Device not in RCM mode, attempting recovery via boardctl (target={boardctl_target})...")
        argv = ["boardctl", "-t", boardctl_target]
        if boardctl_serial:
            argv += ["-s", boardctl_serial]
        status = runner.run([*argv, "recovery"], env=env)
        if status == 0:
            attempted = True
        else:
            log(f"WARNING: boardctl failed (exit {status}) - device may not be connected or TOPO not detected")
            log("Falling back to waiting for manual recovery...")

    if attempted:
        log("Waiting for device to enter RCM mode...")
    else:
        log("Please put device into recovery mode (hold recovery button, press reset)...")
    for _ in range(polls):
        failures.clear()
        boards = _poll(runner, env, failures)
        if boards:
            break
        # A program that is missing now will not appear while waiting.
        if failures and failures[-1].status == CANNOT_START:
            raise failures[-1]
        sleep(1)
    else:
        failures.clear()
        boards = _poll(runner, env, failures)
    if not boards:
        if failures:
            raise failures[-1]
        raise EngineError(f"Device did not enter RCM mode (waited {polls}s)")
    log("Device in RCM mode")
    return boards[0]
