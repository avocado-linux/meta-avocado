"""Locate and validate the flash inputs named by the machine's manifest template.

Standard library only. Image names always come from the template.
"""

import json
import os
from pathlib import Path

from . import FlashError, InputInfo, Problem

BOOT_MEDIA = ("nvme", "sd")
PROFILE = "tegraflash-nvme"
DIR_KEYS = ("tegraflash_bsp", "tegraflash_engine", "tegraflash_tools", "tegraflash_carrier_bsp")
DEFAULT_TARGET = "avocado-stone"
ENGINE_DIRNAME = "tegraflash-engine"
ENGINE_ENTRY = "avocado_tegraflash/__main__.py"

BUILD_TARGETS = {
    "rootfs": "avocado-image-rootfs",
    "var": "avocado-image-var",
    "initramfs": "avocado-image-initramfs",
    "tegraflash_initramfs": "tegra-initrd-flash-initramfs",
    "tegraflash_esp": "tegra-espimage",
    "tegraflash_tos": "tos-optee",
    "tegraflash_bsp": "tegraflash-bsp",
    "tegraflash_engine": "tegraflash-engine",
    "tegraflash_tools": "tegraflash-tools-deploy",
    "tegraflash_carrier_bsp": "tegraflash-bsp",
}


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
    """The string-valued entries of storage_devices.rootdisk.images; a malformed template yields none."""
    node = template
    for section in ("storage_devices", "rootdisk", "images"):
        node = node.get(section) if isinstance(node, dict) else None
    if not isinstance(node, dict):
        return {}
    return {k: v for k, v in node.items() if isinstance(v, str)}


def profile_for(media: str) -> str:
    return f"tegraflash-{media}"


def require_profile(template: dict, machine: str, profile: str = PROFILE) -> None:
    profiles = template.get("provision", {}).get("profiles", {})
    if profile not in profiles:
        raise FlashError(
            f"the manifest template for {machine} has no {profile} profile; "
            "this machine cannot be flashed this way by this tool"
        )


def require_engine(template: dict, machine: str) -> None:
    value = image_entries(template).get("tegraflash_engine")
    if value is None:
        raise FlashError(
            f"the manifest template {template_name(machine)} for {machine} predates "
            "the engine: it does not name the tegraflash_engine directory, so the "
            f"image tree was built before the engine existed; rebuild it with the "
            f"{DEFAULT_TARGET} target"
        )
    if value != ENGINE_DIRNAME:
        # The provisioning shim looks for exactly this name in the data directory.
        raise FlashError(
            f"the manifest template {template_name(machine)} for {machine} names the "
            f"engine directory {value}, but the provisioning script only looks for "
            f"{ENGINE_DIRNAME}; rebuild the image tree with the {DEFAULT_TARGET} target"
        )


def _present(path: Path, key: str) -> bool:
    if key == "tegraflash_engine":
        return (path / ENGINE_ENTRY).is_file()
    if key in DIR_KEYS:
        return path.is_dir()
    return path.is_file() and path.stat().st_size > 0


def check_images(images_dir, entries: dict[str, str]) -> list[Problem]:
    problems = []
    for key, name in entries.items():
        if _present(Path(images_dir) / name, key):
            continue
        kind = "directory" if key in DIR_KEYS else "image"
        hint = (
            f" (it must hold {ENGINE_ENTRY}); the {DEFAULT_TARGET} target deploys it"
            if key == "tegraflash_engine"
            else ""
        )
        problems.append(
            Problem(
                f"{kind} {name} ({key}) is missing, empty or not a {'directory' if key in DIR_KEYS else 'regular file'} in {images_dir}{hint}",
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
