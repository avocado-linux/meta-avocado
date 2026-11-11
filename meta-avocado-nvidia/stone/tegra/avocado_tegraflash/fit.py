"""Refuse an image that does not fit its partition in the staged layout.

Port of the host wrapper's prereqs.fit_report, kept stdlib-only so the engine
does not import from scripts/. The layout decides what the provisioning script
erases and writes, so an absent, unparseable or non-numeric answer refuses
instead of passing unchecked.
"""

import os
import re
import stat
import xml.etree.ElementTree as ET  # nosemgrep: python.lang.security.use-defused-xml.use-defused-xml
from collections.abc import Callable
from pathlib import Path

from . import EngineError
from .manifest import ESP_IMAGE_NAME, Manifest, staged_names
from .plainenv import read_plain_env
from .settings import ENV_FILE, EXTERNAL_LAYOUT

# manifest image key -> partition name in the layout
FIT_PAIRS = (("rootfs", "APP"), ("tegraflash_esp", "esp"))
# initrd-flash writes the rootfs image into both slots, so the smaller one limits it.
ROOTFS_SLOTS = ("APP", "APP_b")
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


def _parse_layout(path) -> tuple[dict, dict, str | None]:
    """Each partition's size (an int, the raw text when not numeric, or DUPLICATE) and <filename>."""
    try:
        with open(path, "rb") as fh:
            data = fh.read(MAX_LAYOUT_BYTES + 1)
    except OSError as exc:
        return {}, {}, str(exc)
    if len(data) > MAX_LAYOUT_BYTES:
        return {}, {}, f"the layout is larger than {MAX_LAYOUT_BYTES} bytes"
    text, reason = _plain_text(data)
    if text is None:
        return {}, {}, reason
    lowered = text.lower()
    if "<!doctype" in lowered or "<!entity" in lowered:
        return {}, {}, "will not parse a layout with a DOCTYPE or entity declaration"
    try:
        # The layout is untrusted; this parse only runs after the size cap, the
        # plain-text check and the DOCTYPE/ENTITY refusal above, so no entity
        # can be defined.
        root = ET.fromstring(data)  # nosemgrep: python.lang.security.use-defused-xml-parse.use-defused-xml-parse
    except ET.ParseError as exc:
        return {}, {}, str(exc)
    sizes: dict = {}
    filenames: dict = {}
    for part in root.iter("partition"):
        name = part.get("name")
        if name is None:
            continue
        if name in sizes:
            sizes[name] = DUPLICATE
            continue
        filenames[name] = (part.findtext("filename") or "").strip()
        raw = (part.findtext("size") or "").strip()
        try:
            sizes[name] = int(raw, 0)
        except ValueError:
            sizes[name] = raw
    return sizes, filenames, None


def _measure(work_dir: Path, name: str) -> int | str:
    """The size of a staged regular file, or the reason it cannot be measured."""
    try:
        st = os.stat(work_dir / name)
    except OSError as exc:
        return str(exc)
    if not stat.S_ISREG(st.st_mode):
        return f"{work_dir / name} is not a regular file"
    return st.st_size


def _rename_collisions(layout: Path, filenames: dict, manifest: Manifest, rootfs_name: str) -> list[str]:
    """Names the flash's own `<rootfs stem>.img` -> rootfs rename would also rewrite.

    initrd-flash.sh turns a pre-signed sparse image name back into the raw one
    with an unanchored sed whose pattern is `${ROOTFS_IMAGE%.*}.img`, so a `.`
    matches any character and any layout entry or staged image that matches it
    is rewritten into the rootfs name.
    """
    sparse = rootfs_name.rsplit(".", 1)[0] + ".img"
    if sparse == rootfs_name:
        return []
    try:
        pattern = re.compile(sparse)
    except re.error as exc:
        return [f"the rootfs name {rootfs_name!r} is not usable in the flash's rename pattern {sparse!r}: {exc}"]
    found = []
    for part, named in filenames.items():
        if named and pattern.search(named):
            found.append(
                f"partition {part} in {layout} names {named!r}, which matches {sparse!r}; the flash would "
                f"rewrite it into the rootfs name {rootfs_name!r}"
            )
    for key, names in staged_names(manifest).items():
        for name in names if key != "rootfs" else ():
            if pattern.search(name):
                found.append(
                    f"images.{key} is staged as {name!r}, which matches {sparse!r}; the flash's rename "
                    f"of that pattern into the rootfs name {rootfs_name!r} would also rewrite it"
                )
    return found


def require_fit(work_dir: str | Path, manifest: Manifest, log: Log = print) -> None:
    work_dir = Path(work_dir)
    layout = work_dir / EXTERNAL_LAYOUT
    if not layout.is_file():
        raise EngineError(f"the partition fit cannot be verified: {layout} is absent")
    sizes, filenames, error = _parse_layout(layout)
    if error is not None:
        raise EngineError(f"the partition fit cannot be verified: {layout} is unreadable ({error})")
    env_file = work_dir / ENV_FILE
    if not env_file.is_file():
        raise EngineError(f"the partition fit cannot be verified: {env_file} is absent")

    problems: list[str] = []
    lines: list[str] = []
    rootfs_name = os.path.basename(manifest.rootfs)
    env_rootfs = read_plain_env(env_file).get("ROOTFS_IMAGE")
    if env_rootfs is not None and env_rootfs != rootfs_name:
        problems.append(
            f"ROOTFS_IMAGE in {env_file} is {env_rootfs!r} but the engine staged and measured {rootfs_name!r}; "
            "the flash would write a different file into the partition"
        )
    esp_file = filenames.get("esp")
    if esp_file is not None and esp_file != ESP_IMAGE_NAME:
        problems.append(
            f"the esp partition in {layout} "
            + (f"names {esp_file!r}" if esp_file else "has no <filename>")
            + f" but the engine staged and measured {ESP_IMAGE_NAME!r}"
        )
    # initrd-flash substitutes the rootfs file only where the layout says APPFILE,
    # so any other name writes a file the engine never measured into the slot.
    for part, placeholder in (("APP", "APPFILE"), ("APP_b", "APPFILE_b")):
        named = filenames.get(part)
        if named and named not in (placeholder, rootfs_name):
            problems.append(
                f"partition {part} in {layout} names {named!r}, which is neither {placeholder!r} "
                f"nor the staged rootfs {rootfs_name!r}; the flash would write a file the engine did not measure"
            )
    # The flash runs the same sed over every line of its layout copy, so the
    # placeholder is rewritten in any partition that carries it, not just the two slots.
    for part, named in filenames.items():
        if part not in ROOTFS_SLOTS and "APPFILE" in named:
            problems.append(
                f"partition {part} in {layout} names {named!r}, which contains APPFILE; the flash would "
                f"replace that text with the rootfs name {rootfs_name!r} and write the rootfs into {part}"
            )
    problems.extend(_rename_collisions(layout, filenames, manifest, rootfs_name))
    images = {"rootfs": rootfs_name, "tegraflash_esp": ESP_IMAGE_NAME if manifest.tegraflash_esp else ""}
    for key, part in FIT_PAIRS:
        name = images[key]
        if not name:
            problems.append(f"manifest names no file for {key}, so its fit in partition {part} cannot be checked")
            continue
        slots = [p for p in (ROOTFS_SLOTS if key == "rootfs" else (part,)) if p in sizes]
        if part not in sizes:
            problems.append(f"partition {part} is absent from the layout {layout}, so {key} {name} cannot be checked")
            continue
        usable = []
        for slot in slots:
            size = sizes[slot]
            if size is DUPLICATE:
                problems.append(f"partition {slot} is listed more than once in {layout}, so its size is ambiguous")
            elif not isinstance(size, int):
                problems.append(
                    f"the size of partition {slot} in {layout} is {size!r}, not a number, "
                    f"so the fit of {key} {name} cannot be verified"
                )
            else:
                usable.append((size, slot))
        if len(usable) != len(slots):
            continue
        size, slot = min(usable, key=lambda pair: pair[0])
        image_size = _measure(work_dir, name)
        if isinstance(image_size, str):
            problems.append(f"{key} image {name} cannot be measured: {image_size}")
        elif image_size > size:
            problems.append(
                f"{key} image {name} ({image_size} bytes) does not fit partition {slot} ({size} bytes)"
            )
        else:
            lines.append(f"fit: {key} {image_size} <= {slot} {size}")
    if problems:
        raise EngineError("\n".join(problems))
    for line in lines:
        log(line)
