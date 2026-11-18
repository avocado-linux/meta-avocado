"""The ums session: start the board's USB mass storage export, find the disk, release it.

    ums_session(host, port, controller, dev, log=print, ...) -> context manager
        yields "/dev/<name>" for AVOCADO_PROVISION_DEVICE

`host` is the console driver avocado-flash already holds, passed in rather than
copied (the script has no .py extension and cannot be imported): UBoot,
interrupt_to_uboot, ums_expose, ums_release, block_devices, and optionally
usb_gadget_present. The session adds the launcher's contract on top of it:
a stale export is stopped before the first listing, the exported disk is the
single whole disk absent from the earlier listing, and the export is released
on every exit once it was started - and never otherwise.
"""

from __future__ import annotations

import contextlib
import time

from avocado_flash_launch.envmap import LauncherError

__all__ = ["ums_session"]

_NOT_DISKS = ("loop", "ram", "zram")


def _whole_disks(names):
    return {n for n in names if not n.startswith(_NOT_DISKS)}


def _gadget_present(host):
    probe = getattr(host, "usb_gadget_present", None)
    if probe is None:
        return False
    try:
        return bool(probe())
    except Exception:
        return False


def _stop_stale_export(host, ub, log, sleep, clock, stale_wait):
    # The host may not offer a probe; then there is nothing it can tell us about a stale export.
    probe = getattr(host, "usb_gadget_present", None)
    if probe is None or not probe():
        return
    log("a UMS export is already running; releasing it first")
    host.ums_release(ub, quiet=True)
    deadline = clock() + stale_wait
    while probe():
        if clock() >= deadline:
            raise LauncherError(
                "an earlier UMS export is still present after the wait; "
                "unplug the OTG cable and run again"
            )
        sleep(0.5)


@contextlib.contextmanager
def ums_session(
    host,
    port,
    controller,
    dev,
    log=print,
    sleep=time.sleep,
    clock=time.monotonic,
    stale_wait=15.0,
):
    ub = host.UBoot(port)
    host.interrupt_to_uboot(ub)
    _stop_stale_export(host, ub, log, sleep, clock, stale_wait)

    before = _whole_disks(host.block_devices())
    # The real ums_expose sends the command and only then raises on several/no new disks,
    # so a raise may leave the board exporting. Release only when a gadget is observed.
    try:
        host.ums_expose(ub, controller, dev)
    except BaseException:
        if _gadget_present(host):
            host.ums_release(ub, quiet=True)
        raise
    try:
        new = sorted(_whole_disks(host.block_devices()) - before)
        if len(new) > 1:
            raise LauncherError(
                "several new disks appeared while exporting UMS "
                f"({' '.join('/dev/' + n for n in new)}); refusing rather than guessing "
                "which is the board"
            )
        if not new:
            raise LauncherError(
                f"no exported disk appeared after 'ums {controller} {dev}'; "
                "check the OTG cable and that the medium exists"
            )
        yield f"/dev/{new[0]}"
    finally:
        host.ums_release(ub)
