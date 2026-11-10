"""Refuse an image that does not fit its partition in the staged layout.

Port of the host wrapper's prereqs.fit_report, kept stdlib-only so the engine
does not import from scripts/. The layout decides what the provisioning script
erases and writes, so an absent, unparseable or non-numeric answer refuses
instead of passing unchecked.
"""

import os
import re
import xml.etree.ElementTree as ET  # nosemgrep: python.lang.security.use-defused-xml.use-defused-xml
from collections.abc import Callable
from pathlib import Path

from . import EngineError
from .manifest import Manifest
from .settings import EXTERNAL_LAYOUT

ESP_IMAGE_NAME = "esp.img"
# manifest image key -> partition name in the layout
FIT_PAIRS = (("rootfs", "APP"), ("tegraflash_esp", "esp"))
MAX_LAYOUT_BYTES = 4 * 1024 * 1024
_PLAIN_ENCODINGS = ("utf-8", "us-ascii")
_ENCODING_DECL = re.compile(
    r"""^\s*<\?xml[^>]*?\sencoding\s*=\s*["']([^"']*)["']""", re.IGNORECASE
)

Log = Callable[[str], None]


class _Duplicate:
    """Marks a partition name listed more than once in a layout."""


DUPLICATE = _Duplicate()


def _plain_text(data: bytes) -> tuple[str | None, str | None]:
    """Return the layout as text, or a reason it is not plain UTF-8/ASCII.

    A DOCTYPE is found by searching the text, which only works if the bytes
    are what the XML parser will read: UTF-16 or UTF-32 hides it from a text
    search, so those are refused outright.
    """
    not_plain = "will not parse a layout that is not plain UTF-8 or ASCII text"
    if b"\x00" in data or data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return None, f"{not_plain} (UTF-16/UTF-32 or binary content)"
    try:
        text = data.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        return None, f"{not_plain} (invalid UTF-8)"
    declared = _ENCODING_DECL.match(text.lstrip(chr(0xFEFF)))  # a UTF-8 BOM is plain UTF-8
    if declared and declared.group(1).lower() not in _PLAIN_ENCODINGS:
        return None, f"{not_plain} (the XML declaration names {declared.group(1)})"
    return text, None


def parse_partition_sizes(path) -> tuple[dict, str | None]:
    """Map partition name to its size, an int or the raw text when not numeric.

    A name listed more than once maps to DUPLICATE: its size is ambiguous.
    """
    try:
        with open(path, "rb") as fh:
            data = fh.read(MAX_LAYOUT_BYTES + 1)
    except OSError as exc:
        return {}, str(exc)
    if len(data) > MAX_LAYOUT_BYTES:
        return {}, f"the layout is larger than {MAX_LAYOUT_BYTES} bytes"
    text, reason = _plain_text(data)
    if text is None:
        return {}, reason
    lowered = text.lower()
    if "<!doctype" in lowered or "<!entity" in lowered:
        return {}, "will not parse a layout with a DOCTYPE or entity declaration"
    try:
        # The layout is untrusted; this parse only runs after the size cap, the
        # plain-text check and the DOCTYPE/ENTITY refusal above, so no entity
        # can be defined.
        root = ET.fromstring(data)  # nosemgrep: python.lang.security.use-defused-xml-parse.use-defused-xml-parse
    except ET.ParseError as exc:
        return {}, str(exc)
    sizes: dict = {}
    for part in root.iter("partition"):
        name = part.get("name")
        if name is None:
            continue
        if name in sizes:
            sizes[name] = DUPLICATE
            continue
        raw = (part.findtext("size") or "").strip()
        try:
            sizes[name] = int(raw, 0)
        except ValueError:
            sizes[name] = raw
    return sizes, None


def require_fit(work_dir: str | Path, manifest: Manifest, log: Log = print) -> None:
    work_dir = Path(work_dir)
    layout = work_dir / EXTERNAL_LAYOUT
    if not layout.is_file():
        raise EngineError(f"the partition fit cannot be verified: {layout} is absent")
    sizes, error = parse_partition_sizes(layout)
    if error is not None:
        raise EngineError(f"the partition fit cannot be verified: {layout} is unreadable ({error})")

    images = {
        "rootfs": os.path.basename(manifest.rootfs),
        "tegraflash_esp": ESP_IMAGE_NAME if manifest.tegraflash_esp else "",
    }
    problems: list[str] = []
    lines: list[str] = []
    for key, part in FIT_PAIRS:
        name = images[key]
        if not name:
            continue
        size = sizes.get(part)
        if size is DUPLICATE:
            problems.append(f"partition {part} is listed more than once in {layout}, so its size is ambiguous")
            continue
        if part not in sizes:
            problems.append(f"partition {part} is absent from the layout {layout}, so {key} {name} cannot be checked")
            continue
        if not isinstance(size, int):
            problems.append(
                f"the size of partition {part} in {layout} is {size!r}, not a number, "
                f"so the fit of {key} {name} cannot be verified"
            )
            continue
        try:
            image_size = os.stat(work_dir / name).st_size
        except OSError as exc:
            problems.append(f"{key} image {name} cannot be measured: {exc}")
            continue
        if image_size > size:
            problems.append(
                f"{key} image {name} ({image_size} bytes) does not fit partition {part} ({size} bytes)"
            )
        else:
            lines.append(f"fit: {key} {image_size} <= {part} {size}")
    if problems:
        raise EngineError("\n".join(problems))
    for line in lines:
        log(line)
