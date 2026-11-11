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
from typing import NamedTuple

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


class _Layout(NamedTuple):
    """What the checks read from a layout.

    `sizes` is keyed by partition name (a repeated name is DUPLICATE); `parts` lists every partition element in order, named
    or not, because the flash's sed rewrites every line whatever the name.
    """

    sizes: dict
    parts: list  # of (name or None, <filename> text)
    oem_signed: bool
    error: str | None


def _failed(reason: str) -> _Layout:
    return _Layout({}, [], False, reason)


def _parse_layout(path) -> _Layout:
    """Each partition's size (an int, the raw text when not numeric, or DUPLICATE) and <filename>."""
    try:
        with open(path, "rb") as fh:
            data = fh.read(MAX_LAYOUT_BYTES + 1)
    except OSError as exc:
        return _failed(str(exc))
    if len(data) > MAX_LAYOUT_BYTES:
        return _failed(f"the layout is larger than {MAX_LAYOUT_BYTES} bytes")
    text, reason = _plain_text(data)
    if text is None:
        return _failed(reason)
    lowered = text.lower()
    if "<!doctype" in lowered or "<!entity" in lowered:
        return _failed("will not parse a layout with a DOCTYPE or entity declaration")
    try:
        # The layout is untrusted; this parse only runs after the size cap, the
        # plain-text check and the DOCTYPE/ENTITY refusal above, so no entity
        # can be defined.
        root = ET.fromstring(data)  # nosemgrep: python.lang.security.use-defused-xml-parse.use-defused-xml-parse
    except ET.ParseError as exc:
        return _failed(str(exc))
    sizes: dict = {}
    parts: list = []
    for part in root.iter("partition"):
        name = part.get("name")
        parts.append((name, (part.findtext("filename") or "").strip()))
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
    # initrd-flash.sh greps the text for this exact attribute, comments included.
    return _Layout(sizes, parts, 'oem_sign="true"' in text, None)


def _measure(work_dir: Path, name: str) -> int | str:
    """The size of a staged regular file, or the reason it cannot be measured."""
    try:
        st = os.stat(work_dir / name)
    except OSError as exc:
        return str(exc)
    if not stat.S_ISREG(st.st_mode):
        return f"{work_dir / name} is not a regular file"
    return st.st_size


# The partition that carries DATAFILE and the ones that carry DTB_FILE in every shipped layout
# (recipes-bsp/tegra-binaries/tegra-storage-layout/*.xml): the flash substitutes the data image and
# the kernel dtb by text, so the same text in any other partition is a file written where nobody meant it.
DATA_PARTITION = "DATAPART_EXPAND"
_KERNEL_DTB_PARTITION = re.compile(r"(?:[AB]_)?kernel-dtb")


def _label(name: str | None) -> str:
    return f"partition {name}" if name is not None else "a partition with no name"


def _rename_pattern(rootfs_name: str) -> re.Pattern:
    """The flash's `${ROOTFS_IMAGE%.*}.img` as GNU sed reads it in a basic regex.

    Only `.` is special in the names the env reader accepts, and `+ ? ( ) { |`
    are literal in a BRE, so escape everything and then let `.` match any
    character again.
    """
    return re.compile(re.escape(rootfs_name.rsplit(".", 1)[0] + ".img").replace(r"\.", "."))


def _rename_collisions(
    layout: Path, parts: list, manifest: Manifest, rootfs_name: str, tos_destination: str = ""
) -> list[str]:
    """Names the flash's own `<rootfs stem>.img` -> rootfs rename would also rewrite.

    initrd-flash.sh turns a pre-signed sparse image name back into the raw one
    with an unanchored sed whose pattern is `${ROOTFS_IMAGE%.*}.img`, so a `.`
    matches any character and any layout entry or staged image that matches it
    is rewritten into the rootfs name. A layout entry that is exactly the rootfs
    name is rewritten into itself and passes.
    """
    pattern = _rename_pattern(rootfs_name)
    sparse = pattern.pattern
    found = []
    for part, named in parts:
        if named and named != rootfs_name and pattern.search(named):
            found.append(
                f"{_label(part)} in {layout} names {named!r}, which matches {sparse!r}; the flash would "
                f"rewrite it into the rootfs name {rootfs_name!r}"
            )
    for key, names in staged_names(manifest, tos_destination).items():
        for name in names if key != "rootfs" else ():
            if pattern.search(name):
                found.append(
                    f"images.{key} is staged as {name!r}, which matches {sparse!r}; the flash's rename "
                    f"of that pattern into the rootfs name {rootfs_name!r} would also rewrite it"
                )
    return found


def _placeholder_problems(layout: Path, parts: list, rootfs_name: str) -> list[str]:
    """Filenames the flash's sed over its layout copy would turn into something the engine did not measure."""
    problems = []
    slot_placeholder = {"APP": "APPFILE", "APP_b": "APPFILE_b"}
    for part, named in parts:
        # initrd-flash substitutes the rootfs file only where the layout says APPFILE,
        # so any other name writes a file the engine never measured into the slot.
        if part in slot_placeholder:
            placeholder = slot_placeholder[part]
            if named and named not in (placeholder, rootfs_name):
                problems.append(
                    f"partition {part} in {layout} names {named!r}, which is neither {placeholder!r} "
                    f"nor the staged rootfs {rootfs_name!r}; the flash would write a file the engine did not measure"
                )
            continue
        # The sed runs over every line, so each placeholder is rewritten in any partition that carries it.
        if "APPFILE" in named:
            problems.append(
                f"{_label(part)} in {layout} names {named!r}, which contains APPFILE; the flash would "
                f"replace that text with the rootfs name {rootfs_name!r} and write the rootfs into it"
            )
        if "DATAFILE" in named and part != DATA_PARTITION:
            problems.append(
                f"{_label(part)} in {layout} names {named!r}, which contains DATAFILE; the flash would "
                f"replace that text with the data image name and write it into a partition other than {DATA_PARTITION}"
            )
        if "DTB_FILE" in named and not (part is not None and _KERNEL_DTB_PARTITION.fullmatch(part)):
            problems.append(
                f"{_label(part)} in {layout} names {named!r}, which contains DTB_FILE; the flash would "
                "replace that text with the kernel dtb name and write it into a partition other than the kernel-dtb slots"
            )
    return problems


def require_fit(work_dir: str | Path, manifest: Manifest, log: Log = print) -> None:
    work_dir = Path(work_dir)
    layout = work_dir / EXTERNAL_LAYOUT
    if not layout.is_file():
        raise EngineError(f"the partition fit cannot be verified: {layout} is absent")
    sizes, parts, oem_signed, error = _parse_layout(layout)
    if error is not None:
        raise EngineError(f"the partition fit cannot be verified: {layout} is unreadable ({error})")
    env_file = work_dir / ENV_FILE
    if not env_file.is_file():
        raise EngineError(f"the partition fit cannot be verified: {env_file} is absent")

    problems: list[str] = []
    lines: list[str] = []
    rootfs_name = os.path.basename(manifest.rootfs)
    env = read_plain_env(env_file)
    env_rootfs = env.get("ROOTFS_IMAGE")
    if env_rootfs is not None and env_rootfs != rootfs_name:
        problems.append(
            f"ROOTFS_IMAGE at {env_rootfs.where} is {str(env_rootfs)!r} but the engine staged and measured "
            f"{rootfs_name!r}; the flash would write a different file into the partition"
        )
    if oem_signed:
        problems.append(
            f'{layout} has oem_sign="true", so the flash signs the layout and takes its filenames from the '
            "signed copy; the engine cannot say which file lands in which partition"
        )
    for part, named in parts:
        if part == "esp" and named != ESP_IMAGE_NAME:
            problems.append(
                f"the esp partition in {layout} "
                + (f"names {named!r}" if named else "has no <filename>")
                + f" but the engine staged and measured {ESP_IMAGE_NAME!r}"
            )
    problems.extend(_placeholder_problems(layout, parts, rootfs_name))
    tos = env.get("TOSIMGFILENAME")
    problems.extend(_rename_collisions(layout, parts, manifest, rootfs_name, str(tos) if tos is not None else ""))
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
