"""The real-run flow: warn, confirm, recheck the pin, run the script.

Standard library only. This module starts nothing itself; the script runs
through the injected runner.
"""

import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from . import FlashError, InputInfo, plan, rcm, workdir
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
    infos: list[InputInfo]
    workdir: workdir.Workdir


def _print_warning() -> None:
    print("WARNING: the NVMe will be erased entirely.")
    print("WARNING: QSPI firmware and UEFI variables will be rewritten.")
    print(
        "The current firmware version cannot be read in recovery mode; it "
        "should have been recorded before entering recovery mode."
    )


def _stage_helper(ctx: FlashContext) -> Path:
    bin_dir = ctx.workdir.path / "bin"
    bin_dir.mkdir(exist_ok=True)
    staged = bin_dir / HELPER_NAME
    shutil.copyfile(ctx.helper_source, staged)
    os.chmod(staged, 0o755)
    return bin_dir


def _print_kept(ctx: FlashContext, what: str) -> None:
    print(f"{what}; the board may be mid-write and must be put in recovery mode again.")
    print(f"work directory: {ctx.workdir.path}")
    print(f"log: {ctx.workdir.log}")


def flash(ctx: FlashContext, host, runner, *, assume_yes: bool) -> None:
    _print_warning()

    if not assume_yes:
        payload = f"the Avocado OS image for {ctx.machine} (NVMe, QSPI firmware, UEFI variables)"
        try:
            host.confirm_destructive(ctx.pinned.path, payload, False, False)
        except host.fatal as exc:
            raise FlashError(str(exc)) from exc

    # Only after the confirmation: a board attached while the prompt waited
    # must not be flashed.
    rcm.recheck(ctx.pinned, rcm.list_usb(runner), ctx.expected_id)

    helper_dir = _stage_helper(ctx)
    is_root = os.geteuid() == 0
    invocation = plan.build_invocation(
        images_dir=ctx.images_dir,
        manifest=ctx.manifest,
        script=ctx.script,
        build_dir=ctx.workdir.path,
        kernel_image=ctx.kernel_image,
        helper_dir=helper_dir,
        extra_path_dir=ctx.extra_path_dir,
        is_root=is_root,
        have_sudo=shutil.which("sudo") is not None,
        caller_path=os.environ.get("PATH", ""),
    )

    try:
        rc = runner.stream(invocation, ctx.workdir.log)
    except Interrupted:
        _print_kept(ctx, "interrupted")
        raise

    if rc != 0:
        _print_kept(ctx, f"the provisioning script exited {rc}")
        raise FlashError(f"the provisioning script exited {rc}")

    print(
        "Flash finished. Remove the FC_REC recovery jumper and power-cycle the board."
    )
    left = workdir.cleanup(ctx.workdir, True, runner, is_root)
    if left is not None:
        print(f"work directory left in place: {left}")
