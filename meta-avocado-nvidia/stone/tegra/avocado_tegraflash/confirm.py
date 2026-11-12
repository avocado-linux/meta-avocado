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


def decide_confirmation(force_raw: str | None, terminal: bool) -> str:
    """Return skip, retype or refuse for the raw AVOCADO_PROVISION_FORCE text and terminal state.

    Mirrors meta-avocado-distro/stone/tests/confirm-vectors.tsv (dry run aside). Unset or empty
    with no terminal is "skip": the engine proceeds without asking, logging a note.
    """
    if force_raw == "1":
        return "skip"
    if force_raw == "0":
        return "retype" if terminal else "refuse"
    if force_raw is None or force_raw == "":
        return "retype" if terminal else "skip"
    raise EngineError(f"AVOCADO_PROVISION_FORCE must be 1, 0 or unset, not {force_raw!r}")


def confirm_device(
    board: UsbDevice,
    media: Media,
    *,
    flags: Sequence[str] = (),
    device: str = "",
    erases_mmc: bool = False,
    force: bool | None,
    isatty: Callable[[], bool],
    read: Callable[[str], str],
    log: Callable[[str], None] = print,
) -> None:
    """Make the operator retype the board's `bus:device`, per the force policy.

    force True skips the prompt; False always requires a terminal; None prompts on a terminal
    and otherwise proceeds with a logged note, so unattended runs without the signal still work.
    """
    raw = "" if force is None else ("1" if force else "0")
    decision = decide_confirmation(raw, isatty())
    if decision == "skip":
        if force is None:
            log("device confirmation skipped: no terminal and no AVOCADO_PROVISION_FORCE signal")
        return
    if decision == "refuse":
        raise EngineError("AVOCADO_PROVISION_FORCE=0 requires confirmation but there is no terminal to confirm on")
    expected = f"{board.bus}:{board.device}"
    # The flags, not the profile alone, decide what the flash erases: ERASE_NVME
    # and ERASE_EMMC from the environment add media the operator did not pick.
    # The device node is the profile medium's only: the flag-added media are named without one.
    erased = [f"{media.value} ({device})" if device else media.value]
    added = [
        name for flag, name in (("--erase-nvme", "nvme"), ("--erase-emmc", "emmc")) if flag in flags and name != media.value
    ]
    # initrd-flash.sh also emits erase-mmc from the staged env, with no flag to show for it.
    if erases_mmc and media.value != "emmc" and "emmc" not in added:
        added.append("emmc")
    erased += added
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
