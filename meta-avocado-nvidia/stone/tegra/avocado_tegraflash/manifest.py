"""The keys the engine reads from storage_devices.rootdisk, and their reader."""

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path

from . import EngineError

# Fixed destinations copy_images stages an image under, whatever the manifest names it.
ESP_IMAGE_NAME = "esp.img"
FLASH_INITRAMFS_NAME = "initrd-flash.img"


@dataclass(frozen=True)
class Key:
    section: str
    name: str
    optional: bool
    reason: str


# Declared in one place so the contract test can compare it with the template.
KEYS: tuple[Key, ...] = (
    Key("images", "rootfs", False, ""),
    Key("images", "var", False, ""),
    Key("images", "initramfs", False, ""),
    Key("images", "tegraflash_initramfs", False, ""),
    Key("images", "tegraflash_esp", False, ""),
    Key("images", "tegraflash_tos", False, ""),
    Key("images", "tegraflash_bsp", False, ""),
    Key("images", "tegraflash_tools", False, ""),
    Key("images", "tegraflash_carrier_bsp", False, ""),
    Key(
        "images",
        "dtb",
        True,
        "The BSP's own DTB is used when no override image is named, and the Orin Nano template ships none.",
    ),
    Key("images", "bpmp_dtb", True, "Same fallback for the BPMP device tree."),
    Key(
        "tegraflash",
        "overlays",
        True,
        "Overlay lists are opt-in per carrier board; the stock template applies none and absence is an empty list.",
    ),
    Key("tegraflash", "dce_overlays", True, "Same as overlays, for the DCE device tree overlays."),
    Key("tegraflash", "sd_device", False, ""),
    Key(
        "tegraflash",
        "rcm_ids",
        True,
        "USB vendor:product ids this board may show in recovery mode; a recovery device with another id is refused. Narrows only, and absence is an empty list.",
    ),
)


@dataclass(frozen=True)
class Manifest:
    """Absent or null values read as empty, as jq's `// empty` does."""

    rootfs: str = ""
    var: str = ""
    initramfs: str = ""
    tegraflash_initramfs: str = ""
    tegraflash_esp: str = ""
    tegraflash_tos: str = ""
    tegraflash_bsp: str = ""
    tegraflash_tools: str = ""
    tegraflash_carrier_bsp: str = ""
    dtb: str = ""
    bpmp_dtb: str = ""
    overlays: tuple[str, ...] = ()
    dce_overlays: tuple[str, ...] = ()
    sd_device: str = ""
    rcm_ids: tuple[str, ...] = ()


_LISTS = {"overlays", "dce_overlays", "rcm_ids"}
_USB_ID = re.compile(r"^[0-9a-f]{4}:[0-9a-f]{4}$")


def _object(value: object, path: str) -> dict:
    """An absent or null level reads as empty; any other non-object is jq's index error."""
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise EngineError(f"manifest key {path} must be an object, found {type(value).__name__}")
    return value


def _text(value: object, path: str) -> str:
    if isinstance(value, (dict, list, bool)):
        raise EngineError(f"manifest key {path} must be a string, found {type(value).__name__}")
    return str(value)


def read_manifest(path: str | Path) -> Manifest:
    try:
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise EngineError(f"cannot read manifest {path}: {exc}") from exc
    storage = _object(_object(doc, "(top level)").get("storage_devices"), "storage_devices")
    rootdisk = _object(storage.get("rootdisk"), "storage_devices.rootdisk")
    prefix = "storage_devices.rootdisk"
    values: dict[str, object] = {}
    for key in KEYS:
        where = f"{prefix}.{key.section}"
        value = _object(rootdisk.get(key.section), where).get(key.name)
        if value is None:
            continue
        where = f"{where}.{key.name}"
        if key.name in _LISTS:
            if not isinstance(value, list):
                raise EngineError(f"manifest key {where} must be a list, found {type(value).__name__}")
            items = tuple(_text(item, f"{where}[]") for item in value)
            if key.name == "rcm_ids":
                for item in items:
                    if not _USB_ID.fullmatch(item):
                        raise EngineError(
                            f"manifest key {where} entries must be lowercase vendor:product hex ids like 0955:7523, found {item!r}"
                        )
            values[key.name] = items
        else:
            text = _text(value, where)
            # Every later guard derives the staged file name from the last path
            # component; an empty, "." or ".." one would skip or misdirect them.
            if key.section == "images" and text and os.path.basename(text) in ("", ".", ".."):
                raise EngineError(f"manifest key {where} must end in a file name, found {text!r}")
            values[key.name] = text
    return Manifest(**values)


REQUIRED_IMAGES = (
    "rootfs",
    "var",
    "initramfs",
    "tegraflash_initramfs",
    "tegraflash_esp",
    "tegraflash_tos",
)


def require_image_keys(manifest: Manifest) -> None:
    """Refuse a manifest that names no file for an image the flash needs.

    Deviation required-image-refused: an absent key reads as empty, and every
    later image guard (presence, size, fit) skips an empty name, so the flash
    would otherwise run without that image and without a word.
    """
    missing = [k for k in REQUIRED_IMAGES if not getattr(manifest, k)]
    if missing:
        raise EngineError(
            "manifest names no file for: "
            + ", ".join(f"storage_devices.rootdisk.images.{k}" for k in missing)
        )
    require_distinct_staged_names(manifest)


def staged_names(manifest: Manifest) -> dict[str, tuple[str, ...]]:
    """The file names copy_images stages each named image under, per manifest key.

    The TOS destination is read from the BSP env file at staging time, so only
    its own basename is known here.
    """
    base = os.path.basename
    names: dict[str, tuple[str, ...]] = {}
    for key in ("rootfs", "var", "initramfs", "tegraflash_tos", "bpmp_dtb"):
        if getattr(manifest, key):
            names[key] = (base(getattr(manifest, key)),)
    if manifest.tegraflash_initramfs:
        names["tegraflash_initramfs"] = (FLASH_INITRAMFS_NAME,)
    if manifest.tegraflash_esp:
        names["tegraflash_esp"] = (base(manifest.tegraflash_esp), ESP_IMAGE_NAME)
    if manifest.dtb:
        names["dtb"] = (base(manifest.dtb), f"kernel_{base(manifest.dtb)}")
    return names


def require_distinct_staged_names(manifest: Manifest) -> None:
    """Refuse two images that stage under one name.

    Staging replaces the file, so the later copy silently replaces the earlier
    and the flash writes the wrong image, one the size check never measured.
    """
    owner: dict[str, str] = {}
    for key, names in staged_names(manifest).items():
        for name in names:
            other = owner.setdefault(name, key)
            if other != key:
                raise EngineError(
                    f"images.{other} and images.{key} would both be staged as {name!r}; "
                    "the later copy would replace the earlier one"
                )
