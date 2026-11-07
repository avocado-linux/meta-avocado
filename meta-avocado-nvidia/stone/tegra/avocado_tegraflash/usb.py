"""NVIDIA USB listing and recovery-mode (RCM/APX) detection."""

import re
from collections.abc import Mapping
from dataclasses import dataclass

from . import EngineError
from .runner import Runner

NVIDIA_VENDOR = "0955"
RECOVERY_PIDS = ("7018", "7418", "7019", "7e19", "7023", "7223", "7323", "7423", "7523", "7623")

# lsusb answers in well under a second; the bound only stops a hung bus query from hanging the engine.
LSUSB_TIMEOUT = 5.0
# lsusb -d exits 1 when nothing matches; any other status means the listing itself failed.
_NO_MATCH = 1

_LINE = re.compile(r"^Bus (\d{3}) Device (\d{3}): ID ([0-9a-fA-F]{4}):([0-9a-fA-F]{4})(?:\s+(.*))?$")


@dataclass(frozen=True)
class UsbDevice:
    bus: str
    device: str
    vid: str
    pid: str
    desc: str


class ListingFailed(EngineError):
    """lsusb could not list the bus (missing, unrunnable or timed out), which is not an empty bus."""

    def __init__(self, status: int):
        super().__init__(f"the USB board listing failed (lsusb status {status}); is lsusb installed?")
        self.status = status


def list_nvidia(runner: Runner, env: Mapping[str, str]) -> list[UsbDevice]:
    """Every NVIDIA USB device; raises ListingFailed when lsusb itself failed."""
    status, out = runner.capture(
        ["lsusb", "-d", f"{NVIDIA_VENDOR}:"], env=env, discard_stderr=True, timeout=LSUSB_TIMEOUT
    )
    if status not in (0, _NO_MATCH):
        raise ListingFailed(status)
    devices = []
    for line in out.splitlines():
        match = _LINE.match(line.rstrip())
        if match:
            bus, device, vid, pid, desc = match.groups()
            devices.append(UsbDevice(bus, device, vid, pid, desc or ""))
    return devices


def is_recovery(device: UsbDevice) -> bool:
    """Same rule as the legacy script: APX/RCM in the description, or a listed id."""
    if device.vid.lower() != NVIDIA_VENDOR:
        return False
    desc = device.desc.lower()
    return "apx" in desc or "rcm" in desc or device.pid.lower() in RECOVERY_PIDS
