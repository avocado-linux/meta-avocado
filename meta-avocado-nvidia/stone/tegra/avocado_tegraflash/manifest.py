"""The keys the engine reads from storage_devices.rootdisk, and their reader."""

import json
from dataclasses import dataclass
from pathlib import Path

from . import EngineError


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


_LISTS = {"overlays", "dce_overlays"}


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
            values[key.name] = tuple(_text(item, f"{where}[]") for item in value)
        else:
            values[key.name] = _text(value, where)
    return Manifest(**values)
