"""Boot-device settings for the staged BSP (oracle lines 529-585)."""

import os
import re
from collections.abc import Callable
from pathlib import Path

from . import EngineError, Media
from .files import copy_replacing_link, read_text_preserving, write_text_replacing_link
from .manifest import Manifest
from .plainenv import read_plain_env

ENV_FILE = ".env.initrd-flash"
EMMC_LAYOUT = "internal-flash-emmc.xml"
EXTERNAL_LAYOUT = "external-flash.xml.in"

# [0-9] and fullmatch, not \d and $: a unicode digit or a trailing newline
# must not pass, since the value lands in a file the flash tool sources.
_SD_DEVICE = re.compile(r"mmcblk[0-9]+")


def _rewrite(env_file: Path, values: dict[str, str]) -> None:
    """Replace whole ``KEY=`` lines like ``sed -i 's/^KEY=.*/.../'``; add none.

    A requested key with no line is refused (deviation env-key-missing-refused):
    sed would pass silently and the board would flash with the wrong boot device.
    """
    if not env_file.is_file():
        raise EngineError(f"{ENV_FILE} not found in {env_file.parent}")
    lines = read_text_preserving(env_file).split("\n")
    seen: set[str] = set()
    for i, line in enumerate(lines):
        for key, text in values.items():
            if line.startswith(key + "="):
                lines[i] = f"{key}={text}"
                seen.add(key)
                break
    missing = [key for key in values if key not in seen]
    if missing:
        raise EngineError(f"{', '.join(missing)} not found in {env_file}")
    write_text_replacing_link(
        env_file, "\n".join(lines), encoding="utf-8", errors="surrogateescape", newline=""
    )


def apply_boot_device(
    work_dir: Path,
    media: Media,
    *,
    sd_device: str,
    log: Callable[[str], None] = print,
) -> str:
    """Write the boot device into the staged env file; return the device node chosen."""
    env_file = Path(work_dir) / ENV_FILE
    if media is Media.NVME:
        device, partition = "nvme0n1", "nvme0n1p1"
    elif media is Media.EMMC:
        device, partition = "mmcblk0", "mmcblk0p1"
    else:
        if not sd_device:
            raise EngineError(
                "no SD card device declared for this board. Add "
                "tegraflash.sd_device to the manifest (mmcblk0 on a module "
                "without eMMC, the next MMC index on one that has it) or set "
                "AVOCADO_PROVISION_SD_DEVICE for a one-off run."
            )
        if not _SD_DEVICE.fullmatch(sd_device):
            raise EngineError(
                f"SD card device {sd_device!r} is not a bare mmcblkN name. "
                "Expected e.g. mmcblk0, not a /dev path and not a partition. "
                "Set AVOCADO_PROVISION_SD_DEVICE or the manifest's "
                "tegraflash.sd_device accordingly."
            )
        log(f"SD card device: {sd_device}")
        device, partition = sd_device, f"{sd_device}p1"

    # The oracle writes EXTERNAL_ROOTFS_DRIVE unquoted; keep the bytes.
    _rewrite(
        env_file,
        {
            "BOOTDEV": f'"{partition}"',
            "ROOTFS_DEVICE": f'"{device}"',
            "EXTERNAL_ROOTFS_DRIVE": "1",
        },
    )

    if media is Media.EMMC:
        layout = Path(work_dir) / EMMC_LAYOUT
        if not layout.is_file():
            raise EngineError(f"{EMMC_LAYOUT} not found in BSP")
        copy_replacing_link(layout, Path(work_dir) / EXTERNAL_LAYOUT)
        log(f"Using eMMC flash layout ({EMMC_LAYOUT} -> {EXTERNAL_LAYOUT})")
    return device


def verify_staged_env(work_dir: Path, manifest: Manifest, expected_device: str) -> str:
    """Read the staged env file as the flash will and return the effective ROOTFS_DEVICE.

    Runs once the file is final. The rewrite above matches only column-0 lines,
    but bash takes the last assignment in any form, so the value the profile
    chose is not proof of the value the flash uses.
    """
    env_file = Path(work_dir) / ENV_FILE
    plain = read_plain_env(env_file)
    device = plain.get("ROOTFS_DEVICE")
    if device != expected_device:
        raise EngineError(
            f"ROOTFS_DEVICE in {env_file} is {device!r} but the profile chose {expected_device!r}; "
            "the flash would erase a different device than the one it was asked to"
        )
    datafile = plain.get("DATAFILE")
    var_name = os.path.basename(manifest.var)
    if datafile is not None and datafile != var_name:
        raise EngineError(
            f"DATAFILE in {env_file} is {datafile!r} but the engine staged {var_name!r}; "
            "the flash would write a different file into the data partition"
        )
    return device
