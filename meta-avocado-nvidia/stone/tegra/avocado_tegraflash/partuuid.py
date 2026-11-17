"""Rootfs PARTUUID pins (oracle: stone-provision-tegraflash.sh)."""

import re
from collections.abc import Callable
from pathlib import Path

from . import EngineError
from .files import read_text_preserving, write_text_replacing_link

_UUID_SOURCE = "/proc/sys/kernel/random/uuid"
_ATTEMPTS = 8
_LAYOUT = "external-flash.xml.in"
_SLOT_B = "APPUUID_b"
# APPUUID_b contains APPUUID, so slot A is a placeholder followed by anything
# but an underscore. Matched per line, as the oracle's grep does.
_SLOT_A = re.compile(r"APPUUID[^_]")
_SLOT_A_ANY = re.compile(r"APPUUID(?!_)")

# The writer half of the codec policy of `files.read_text_preserving`.
_IO = {"encoding": "utf-8", "errors": "surrogateescape", "newline": ""}

Source = Callable[[], str]


def _kernel_uuid() -> str:
    with open(_UUID_SOURCE) as fh:
        return fh.read()


def new_pins(source: Source = _kernel_uuid) -> tuple[str, str]:
    """Two distinct uppercase PARTUUIDs, one per rootfs slot."""
    a = source().strip().upper()
    for _ in range(_ATTEMPTS):
        b = source().strip().upper()
        if b != a:
            return a, b
    raise EngineError("the kernel UUID source returned the same value repeatedly")


def append_cmdline(extra: str, pins: tuple[str, str]) -> str:
    pinned = f"avocado.root_partuuid={pins[0]} avocado.root_partuuid_b={pins[1]}"
    return f"{extra} {pinned}" if extra else pinned


def apply_layout(work_dir: str | Path, pins: tuple[str, str]) -> None:
    path = Path(work_dir) / _LAYOUT
    if not path.is_file():
        raise EngineError(f"{path} not found; cannot pin the rootfs PARTUUIDs.")
    text = read_text_preserving(path)
    # A missing placeholder means this is not the templated layout: flashing on
    # would write GUIDs that disagree with the command line already baked.
    for label, present in (
        (_SLOT_B, _SLOT_B in text),
        ("APPUUID[^_]", any(_SLOT_A.search(line) for line in text.split("\n"))),
    ):
        if not present:
            raise EngineError(
                f"{path} has no {label} placeholder.\n"
                "       tegraflash-bsp.bb is expected to leave these for us to\n"
                "       fill; if it blanks them again, the command line names a\n"
                "       rootfs PARTUUID this layout will never produce."
            )
    # str.replace fills every occurrence, so a repeat would give two partitions
    # one GUID. Slot A is counted without the underscore so slot B's is not.
    for label, count in (
        (_SLOT_B, text.count(_SLOT_B)),
        ("APPUUID", len(_SLOT_A_ANY.findall(text))),
    ):
        if count != 1:
            raise EngineError(
                f"{path} has {count} {label} placeholders; each of the two must occur exactly once,\n"
                "       or two partitions would get the same PARTUUID."
            )
    # Slot B first: its placeholder contains slot A's.
    text = text.replace(_SLOT_B, pins[1]).replace("APPUUID", pins[0])
    if "APPUUID" in text:
        raise EngineError(f"APPUUID placeholder survived substitution in {path}.")
    write_text_replacing_link(path, text, **_IO)


def blank_layout(work_dir: str | Path) -> None:
    """Prebuilt boot.img names no PARTUUID; an unblanked placeholder makes sgdisk write zeros."""
    path = Path(work_dir) / _LAYOUT
    if path.is_file():
        text = read_text_preserving(path).replace(_SLOT_B, "").replace("APPUUID", "")
        write_text_replacing_link(path, text, **_IO)
