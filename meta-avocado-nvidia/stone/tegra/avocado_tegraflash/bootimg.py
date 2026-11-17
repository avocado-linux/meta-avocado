"""Repack boot.img from the staged kernel (oracle: stone-provision-tegraflash.sh)."""

import os
import shutil
from collections.abc import Callable, Mapping
from pathlib import Path

from . import EngineError
from .files import materialize_link
from .runner import Runner

Log = Callable[[str], None]

_PREBUILT_WARNING = (
    "AVOCADO_PROVISION_KERNEL_IMAGE not set - using prebuilt boot.img from BSP",
    "WARNING: the prebuilt boot.img names no rootfs PARTUUID. With a boot signal",
    "         (BootCurrent) the initrd takes APP on the disk UEFI booted from.",
    "         With none, the first APP to appear boots, so an SD card that",
    "         enumerates before the NVMe wins. Two or more APP disks are caught",
    "         only if all are present at that moment; then a root= naming",
    "         exactly one of them settles it, and otherwise the initrd stops.",
)


def repack(
    runner: Runner,
    *,
    work_dir: str | Path,
    kernel_image: str,
    initramfs_name: str,
    env: Mapping[str, str],
    version: str,
    log: Log = print,
) -> None:
    if not Path(kernel_image).is_file():
        raise EngineError(f"AVOCADO_PROVISION_KERNEL_IMAGE={kernel_image} not found")
    work = Path(work_dir)
    initramfs = work / os.path.basename(initramfs_name)
    if not initramfs.is_file():
        raise EngineError(f"initramfs cpio not staged at {initramfs}")
    mkbootimg = shutil.which("mkbootimg", path=env.get("PATH", ""))
    if mkbootimg is None:
        raise EngineError("mkbootimg not found on PATH")
    log(f"Packing boot.img from kernel {version or '?'} (Image={kernel_image})")
    boot = f"{work}/boot.img"
    # The helper reads its base image from the path it then writes, so a staged
    # link becomes a copy first and the data directory's own image is not modified.
    materialize_link(boot)
    status = runner.run(
        ["avocado-tegra-bootimg", mkbootimg, boot, kernel_image, str(initramfs), boot],
        env=env,
    )
    if status != 0:
        raise EngineError(f"avocado-tegra-bootimg failed (exit {status})")
    log("boot.img repacked at provision time")


def refuse_cmdline_without_kernel(cmdline: str, extra: str) -> None:
    if cmdline or extra:
        raise EngineError(
            "kernel.cmdline / cmdline_extra is set, but no kernel Image was staged\n"
            "       (AVOCADO_PROVISION_KERNEL_IMAGE) to repack boot.img with it."
        )


def warn_prebuilt_boot_image(log: Log = print) -> None:
    for line in _PREBUILT_WARNING:
        log(line)
