"""Explicit-table layout: sfdisk input text and fit checks.

The layout parameters are the validated output of the "explicit-table"
strategy (see strategies.py). Standard library only.
"""

from __future__ import annotations

import re

GPT_SECONDARY_SECTORS = 34
# One GPT header and its protective MBR sit before the first usable sector.
GPT_MIN_FIRST_LBA = 34
# Partition names and UUIDs are interpolated into a quoted sfdisk script field, so the charset is closed.
PART_NAME_RE = re.compile(r"[A-Za-z0-9_.+-]{1,36}")
GUID_RE = re.compile(r"[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}")


class LayoutError(ValueError):
    """The partition table cannot be created on the target device."""


ESP_TYPE_GUID = "C12A7328-F81F-11D2-BA4B-00A0C93EC93B"


def esp_images(layout_params, images) -> list:
    """The images whose partition carries the EFI System Partition type GUID, whatever their role is called."""
    esp_numbers = {p["number"] for p in layout_params["table"] if p["type_guid"].upper() == ESP_TYPE_GUID}
    return [img for img in images.values() if img.partition in esp_numbers]


NO_ESP_IMAGE = (
    "the profile arms a boot entry but maps no image to an EFI System Partition "
    f"(partition type {ESP_TYPE_GUID})"
)


def partition_node(device_path: str, number: int) -> str:
    """Device node of partition number (mmcblk0 -> mmcblk0p3, sdb -> sdb3)."""
    sep = "p" if device_path[-1:].isdigit() else ""
    return f"{device_path}{sep}{number}"


def _ordered(layout_params):
    return sorted(layout_params["table"], key=lambda p: (p["start"], p["number"]))


def check_fits(layout_params, device_sectors: int) -> None:
    """Re-assert, independent of profile validation, that the table is safe."""
    first = layout_params["first_lba"]
    last = layout_params["last_lba"]
    expected_last = device_sectors - GPT_SECONDARY_SECTORS
    if last != expected_last:
        raise LayoutError(
            f"last_lba {last} must equal device_sectors - {GPT_SECONDARY_SECTORS} "
            f"= {expected_last}"
        )
    prev_end = None
    prev_num = None
    for part in _ordered(layout_params):
        start = part["start"]
        end = start + part["size"] - 1
        if part["size"] <= 0:
            raise LayoutError(f"partition {part['number']}: size must be positive")
        if start < first:
            raise LayoutError(
                f"partition {part['number']}: start {start} is before first_lba {first}"
            )
        if end > last:
            raise LayoutError(
                f"partition {part['number']}: ends at {end}, after last_lba {last}"
            )
        if prev_end is not None and start <= prev_end:
            raise LayoutError(
                f"partitions {prev_num} and {part['number']} overlap "
                f"(start {start} <= end {prev_end})"
            )
        prev_end, prev_num = end, part["number"]


def _check_script_fields(part, mapped_uuid) -> None:
    name = part.get("name")
    if not isinstance(name, str) or not PART_NAME_RE.fullmatch(name):
        raise LayoutError(f"partition {part.get('number')}: name {name!r} must be 1-36 of letters, digits, _ . + -")
    for field in ("uuid", "type_guid"):
        value = part.get(field)
        if value is not None and (not isinstance(value, str) or not GUID_RE.fullmatch(value)):
            raise LayoutError(f"partition {part.get('number')}: {field} {value!r} is not an 8-4-4-4-12 hex GUID")


def sfdisk_input(layout_params, device_path: str, uuids=None) -> str:
    """Return the sfdisk script (no indentation) for the table.

    A partition UUID comes from the partition's optional "uuid" field or from
    the uuids mapping (number -> UUID); the mapping wins when both are given.
    """
    uuids = dict(uuids or {})
    for part in layout_params["table"]:
        _check_script_fields(part, uuids.get(part["number"]))
    numbers = {p["number"] for p in layout_params["table"]}
    for n, u in uuids.items():
        if not isinstance(u, str) or not GUID_RE.fullmatch(u):
            raise LayoutError(f"uuid {u!r} for partition {n} is not an 8-4-4-4-12 hex GUID")
        if n not in numbers:
            raise LayoutError(f"uuid given for unknown partition {n}")
    sectors = layout_params.get("device_sectors")
    if isinstance(sectors, bool) or not isinstance(sectors, int) or sectors <= 0:
        raise LayoutError(f"device_sectors {sectors!r} must be a positive integer")
    check_fits(layout_params, sectors)

    out = [
        "label: gpt",
        f"first-lba: {layout_params['first_lba']}",
        f"last-lba: {layout_params['last_lba']}",
        f"sector-size: {layout_params.get('sector_size', 512)}",
        "",
    ]
    for part in _ordered(layout_params):
        n = part["number"]
        line = (
            f"{partition_node(device_path, n)} : start={part['start']}, "
            f"size={part['size']}, type={part['type_guid']}"
        )
        uuid = uuids.get(n, part.get("uuid"))
        if uuid:
            line += f", uuid={uuid}"
        out.append(f'{line}, name="{part["name"]}"')
    return "\n".join(out) + "\n"
