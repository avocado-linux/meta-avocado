"""The real-run flow: warn, confirm, recheck the pin, run the script.

Standard library only. This module starts nothing itself; the script runs
through the injected runner.
"""

import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from . import FlashError, plan, rcm, workdir
from .runner import Interrupted

HELPER_NAME = "avocado-tegra-bootimg"


@dataclass
class FlashContext:
    machine: str
    images_dir: Path
    manifest: Path
    script: Path
    kernel_image: Path
    helper_source: Path
    extra_path_dir: Path | None
    expected_id: str
    pinned: rcm.UsbDevice
    workdir: workdir.Workdir


def _print_warning() -> None:
    print("WARNING: the NVMe will be erased entirely.")
    print("WARNING: QSPI firmware and UEFI variables will be rewritten.")
    print(
        "The current firmware version cannot be read in recovery mode; it "
        "should have been recorded before entering recovery mode."
    )


def _stage_helper(ctx: FlashContext, stat_fn=os.lstat) -> Path:
    """Place the boot image helper where root will execute it from.

    Everything here is created by us: a pre-existing ``bin`` must be a private
    directory we own, and a pre-existing helper (a symlink included) is
    unlinked rather than written through.
    """
    bin_dir = ctx.workdir.path / "bin"
    if os.path.lexists(bin_dir):
        workdir.require_private_dir(bin_dir, stat_fn)
    else:
        try:
            os.mkdir(bin_dir, 0o700)
        except OSError as exc:
            raise FlashError(f"cannot create {bin_dir}: {exc}") from exc
    staged = bin_dir / HELPER_NAME
    try:
        try:
            os.unlink(staged)
        except FileNotFoundError:
            pass
        fd = os.open(staged, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o755)
        with os.fdopen(fd, "wb") as out:
            out.write(ctx.helper_source.read_bytes())
            os.fchmod(out.fileno(), 0o755)  # nosemgrep: python.lang.security.audit.insecure-file-permissions.insecure-file-permissions - helper must be executable by the root-run script; its directory is private 0o700
    except OSError as exc:
        raise FlashError(f"cannot stage the boot image helper in {bin_dir}: {exc}") from exc
    return bin_dir


def _discard_workdir(ctx: FlashContext) -> None:
    """Best-effort removal of a directory this run created and never used."""
    if not ctx.workdir.created_by_tool:
        return
    bin_dir = ctx.workdir.path / "bin"
    for remove, target in (
        (os.unlink, bin_dir / HELPER_NAME),
        (os.rmdir, bin_dir),
        (os.rmdir, ctx.workdir.path),
    ):
        try:
            remove(target)
        except OSError:
            pass


def _print_kept(ctx: FlashContext, what: str) -> None:
    print(f"{what}; the board may be mid-write and must be put in recovery mode again.")
    print(f"work directory: {ctx.workdir.path}")
    print(f"log: {ctx.workdir.log}")


def _prepare(ctx: FlashContext, host, runner, assume_yes: bool, is_root: bool, have_sudo: bool):
    """Everything that must pass before the script starts."""
    _print_warning()

    if not assume_yes:
        payload = f"the Avocado OS image for {ctx.machine} (NVMe, QSPI firmware, UEFI variables)"
        # The shared prompt only says "the target"; the path it compares
        # against otherwise appears once, in the banner above it.
        print(f"To confirm, type: {ctx.pinned.path}")
        try:
            host.confirm_destructive(ctx.pinned.path, payload, False, False)
        except host.fatal as exc:
            raise FlashError(str(exc)) from exc

    # After the confirmation, so a prompt left open past sudo's timeout cannot
    # leave the script's own sudo asking for a password after the recheck.
    if not is_root and have_sudo:
        rc, _ = runner.capture(["sudo", "-v"])
        if rc != 0:
            raise FlashError("could not obtain root: sudo authentication failed")

    # Only after the confirmation: a board attached while the prompt waited
    # must not be flashed.
    rcm.recheck(ctx.pinned, rcm.list_usb(runner), ctx.expected_id)

    helper_dir = _stage_helper(ctx)
    return plan.build_invocation(
        images_dir=ctx.images_dir,
        manifest=ctx.manifest,
        script=ctx.script,
        build_dir=ctx.workdir.path,
        kernel_image=ctx.kernel_image,
        helper_dir=helper_dir,
        extra_path_dir=ctx.extra_path_dir,
        is_root=is_root,
        have_sudo=have_sudo,
        caller_path=os.environ.get("PATH", ""),
    )


def flash(ctx: FlashContext, host, runner, *, assume_yes: bool) -> None:
    is_root = os.geteuid() == 0
    try:
        invocation = _prepare(
            ctx, host, runner, assume_yes, is_root, shutil.which("sudo") is not None
        )
    except BaseException:
        _discard_workdir(ctx)
        raise

    try:
        rc = runner.stream(invocation, ctx.workdir.log)
    except Interrupted:
        _print_kept(ctx, "interrupted")
        raise
    except KeyboardInterrupt as exc:
        # The runner absorbs SIGINT while it waits; this is the backstop for a
        # runner that does not.
        _print_kept(ctx, "interrupted")
        raise Interrupted("interrupted while the provisioning script ran") from exc

    if rc != 0:
        _print_kept(ctx, f"the provisioning script exited {rc}")
        raise FlashError(f"the provisioning script exited {rc}")

    print(
        "Flash finished. Remove the FC_REC recovery jumper and power-cycle the board."
    )
    left = workdir.cleanup(ctx.workdir, True, runner, is_root)
    if left is not None:
        print(f"work directory left in place: {left}")
