"""USB listing, recovery-device pinning and the pre-write recheck.

Standard library only. The listing goes through an injected runner
(``runner.capture(argv) -> (returncode, stdout)``) so this module never
starts a process itself.
"""

import re
from dataclasses import dataclass

from . import FlashError
from .machines import NVIDIA_VENDOR

# A Jetson running Linux in USB device mode, not waiting in recovery mode.
DEVICE_MODE_ID = "0955:7020"

_LINE = re.compile(
    r"^Bus (\d{3}) Device (\d{3}): ID ([0-9a-fA-F]{4}):([0-9a-fA-F]{4})\s*(.*?)\s*$"
)


class ListingFailed(FlashError):
    """The USB listing could not be produced; says nothing about the board."""


class NoRecoveryDevice(FlashError):
    """No NVIDIA device is in recovery mode."""


class MultipleRecoveryDevices(FlashError):
    """More than one NVIDIA device is in recovery mode."""


class DeviceSetChanged(FlashError):
    """The recovery devices at the recheck are not exactly the pinned one."""


@dataclass(frozen=True)
class UsbDevice:
    bus: str
    device: str
    vid: str
    pid: str
    desc: str

    @property
    def id(self) -> str:
        return f"{self.vid}:{self.pid}".lower()

    @property
    def path(self) -> str:
        return f"{self.bus}:{self.device}"


def list_usb(runner) -> list[UsbDevice]:
    """Parse ``lsusb``; a failed listing raises ``ListingFailed``."""
    rc, out = runner.capture(["lsusb"])
    if rc != 0:
        reason = "lsusb could not be started" if rc == 127 else f"lsusb exited {rc}"
        raise ListingFailed(f"USB devices could not be listed ({reason})")
    found = []
    for line in out.splitlines():
        m = _LINE.match(line)
        if m:
            bus, dev, vid, pid, desc = m.groups()
            found.append(UsbDevice(bus, dev, vid.lower(), pid.lower(), desc))
    return found


def _candidates(devices) -> list[UsbDevice]:
    return [d for d in devices if d.vid == NVIDIA_VENDOR and d.id != DEVICE_MODE_ID]


def _describe(d: UsbDevice) -> str:
    return f"{d.path} (id {d.id})"


def pin(devices, expected_id: str) -> UsbDevice:
    """Return the one recovery-mode device, which must carry ``expected_id``."""
    cands = _candidates(devices)
    if not cands:
        text = (
            "no NVIDIA device in recovery mode found: hold the recovery jumper, "
            "connect the USB cable and power-cycle the board"
        )
        if any(d.id == DEVICE_MODE_ID for d in devices):
            text += (
                f". An NVIDIA device with id {DEVICE_MODE_ID} is present: "
                "the board is running Linux and is not in recovery mode"
            )
        raise NoRecoveryDevice(text)
    if len(cands) > 1:
        listed = "\n".join(f"  {_describe(d)}" for d in cands)
        raise MultipleRecoveryDevices(
            "more than one NVIDIA recovery device is attached; "
            f"leave only the board to flash connected:\n{listed}"
        )
    only = cands[0]
    if only.id != expected_id.lower():
        raise FlashError(
            f"recovery device {_describe(only)} does not match the expected "
            f"recovery id {expected_id.lower()}: found {only.id}, expected {expected_id.lower()}"
        )
    return only


def recheck(pinned: UsbDevice, devices, expected_id: str) -> None:
    """Abort unless the recovery candidates are exactly the pinned device."""
    cands = _candidates(devices)
    if cands != [pinned] or pinned.id != expected_id.lower():
        now = ", ".join(_describe(d) for d in cands) or "none"
        raise DeviceSetChanged(
            f"the set of recovery devices changed since {_describe(pinned)} "
            f"was pinned (now: {now}); nothing was started"
        )
