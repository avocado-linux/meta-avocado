"""Operator confirmation before an erasing flash (AVOCADO_PROVISION_FORCE policy)."""

import sys
from collections.abc import Callable, Sequence

from . import EngineError, Media
from .usb import UsbDevice


def stdin_is_tty() -> bool:
    """False when stdin is absent or closed, so the force policy decides, not an AttributeError."""
    stdin = sys.stdin
    try:
        return stdin is not None and stdin.isatty()
    except ValueError:
        return False


def confirm_device(
    board: UsbDevice,
    media: Media,
    *,
    flags: Sequence[str] = (),
    force: bool | None,
    isatty: Callable[[], bool],
    read: Callable[[str], str],
    log: Callable[[str], None] = print,
) -> None:
    """Make the operator retype the board's `bus:device`, per the force policy.

    force True skips the prompt; False always requires a terminal; None prompts on a terminal
    and otherwise proceeds with a logged note, so unattended runs without the signal still work.
    """
    if force is True:
        return
    if not isatty():
        if force is False:
            raise EngineError("AVOCADO_PROVISION_FORCE=0 requires confirmation but there is no terminal to confirm on")
        log("device confirmation skipped: no terminal and no AVOCADO_PROVISION_FORCE signal")
        return
    expected = f"{board.bus}:{board.device}"
    # The flags, not the profile alone, decide what the flash erases: ERASE_NVME
    # and ERASE_EMMC from the environment add media the operator did not pick.
    erased = [media.value]
    for flag, name in (("--erase-nvme", "nvme"), ("--erase-emmc", "emmc")):
        if flag in flags and name not in erased:
            erased.append(name)
    prompt = (
        f"About to ERASE {', '.join(erased)} on the board {board.vid}:{board.pid} (USB {expected}).\n"
        "QSPI firmware and UEFI variables will also be rewritten.\n"
        f"All data on it will be lost. Type {expected} to continue: "
    )
    try:
        typed = read(prompt).strip()
    except EOFError:
        raise EngineError("device confirmation failed: stdin closed before an answer was given") from None
    except KeyboardInterrupt:
        raise EngineError("device confirmation interrupted") from None
    if typed != expected:
        raise EngineError(f"device confirmation failed: typed {typed!r}, expected {expected!r}")
