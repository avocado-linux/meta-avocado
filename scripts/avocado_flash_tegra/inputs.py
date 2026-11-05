"""Locate and validate the flash inputs named by the machine's manifest template.

Standard library only. Image names always come from the template.
"""

import json
import os
from pathlib import Path

from . import FlashError, InputInfo, Problem

BOOT_MEDIA = ("nvme", "sd")
PROFILE = "tegraflash-nvme"
DIR_KEYS = ("tegraflash_bsp", "tegraflash_tools", "tegraflash_carrier_bsp")
DEFAULT_TARGET = "avocado-stone"

BUILD_TARGETS = {
    "rootfs": "avocado-image-rootfs",
    "var": "avocado-image-var",
    "initramfs": "avocado-image-initramfs",
    "tegraflash_initramfs": "tegra-initrd-flash-initramfs",
    "tegraflash_esp": "tegra-espimage",
    "tegraflash_tos": "tos-optee",
    "tegraflash_bsp": "tegraflash-bsp",
    "tegraflash_tools": "tegraflash-tools-deploy",
    "tegraflash_carrier_bsp": "tegraflash-bsp",
}


def validate_cmdline_extra(value: str) -> str:
    """Return the extra kernel arguments unchanged, or refuse a value the boot image cannot carry.

    The text is written into a boot image's command line by a script that runs as root, so a newline
    or another control character would be read as more than arguments.
    """
    if not value.strip():
        raise FlashError("invalid --kernel-cmdline-extra: it is empty")
    if any(ord(c) < 0x20 or ord(c) == 0x7F for c in value):
        raise FlashError("invalid --kernel-cmdline-extra: it contains a control character or a newline")
    return value


def template_name(machine: str) -> str:
    return f"stone-{machine.removeprefix('avocado-')}.json"


def load_template(images_dir, machine: str) -> dict:
    name = template_name(machine)
    path = Path(images_dir) / name
    if not path.is_file():
        raise FlashError(
            f"manifest template {name} not found in {images_dir}; build the "
            f"{DEFAULT_TARGET} target to deploy it. A bring-up build also "
            "lacks the provisioning script, the var, ESP and TOS images and "
            "the host tools."
        )
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        raise FlashError(f"cannot read manifest template {path}: {exc}") from exc


def image_entries(template: dict) -> dict[str, str]:
    images = template.get("storage_devices", {}).get("rootdisk", {}).get("images", {})
    return {k: v for k, v in images.items() if isinstance(v, str)}


def profile_for(media: str) -> str:
    return f"tegraflash-{media}"


def require_profile(template: dict, machine: str, profile: str = PROFILE) -> None:
    profiles = template.get("provision", {}).get("profiles", {})
    if profile not in profiles:
        raise FlashError(
            f"the manifest template for {machine} has no {profile} profile; "
            "this machine cannot be flashed this way by this tool"
        )


def _present(path: Path, key: str) -> bool:
    if key in DIR_KEYS:
        return path.is_dir()
    return path.is_file() and path.stat().st_size > 0


def check_images(images_dir, entries: dict[str, str]) -> list[Problem]:
    problems = []
    for key, name in entries.items():
        if _present(Path(images_dir) / name, key):
            continue
        kind = "directory" if key in DIR_KEYS else "image"
        problems.append(
            Problem(
                f"{kind} {name} ({key}) is missing, empty or not a {'directory' if key in DIR_KEYS else 'regular file'} in {images_dir}",
                BUILD_TARGETS.get(key, DEFAULT_TARGET),
            )
        )
    return problems


def _dir_size(path: Path) -> int:
    total = 0
    for root, _dirs, files in os.walk(path, followlinks=True):
        for f in files:
            try:
                total += os.stat(os.path.join(root, f)).st_size
            except OSError:
                pass
    return total


def describe_inputs(images_dir, entries: dict[str, str]) -> list[InputInfo]:
    infos = []
    for key, name in entries.items():
        path = Path(images_dir) / name
        st = path.stat()
        size = _dir_size(path) if path.is_dir() else st.st_size
        infos.append(InputInfo(name=name, key=key, size=size, mtime=st.st_mtime))
    return infos
