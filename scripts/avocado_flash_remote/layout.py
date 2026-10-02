"""Explicit-table layout: sfdisk input text and fit checks.

The layout parameters are the validated output of the "explicit-table"
strategy (see strategies.py). Standard library only.
"""

from __future__ import annotations

GPT_SECONDARY_SECTORS = 34


class LayoutError(ValueError):
    """The partition table cannot be created on the target device."""


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


def sfdisk_input(layout_params, device_path: str, uuids=None) -> str:
    """Return the sfdisk script (no indentation) for the table.

    A partition UUID comes from the partition's optional "uuid" field or from
    the uuids mapping (number -> UUID); the mapping wins when both are given.
    """
    uuids = dict(uuids or {})
    numbers = {p["number"] for p in layout_params["table"]}
    for n in uuids:
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
