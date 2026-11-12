"""Checks for the executables, helper and host tools the flash needs.

Standard library only. The only process started is the one-line version probe
of the python3 found on the search path.
"""

import os
import re
import shutil
import subprocess
import tempfile
import xml.etree.ElementTree as ET  # nosemgrep: python.lang.security.use-defused-xml.use-defused-xml
from pathlib import Path

from . import Problem
from .inputs import BUILD_TARGETS, PROFILE, image_entries

HELPER_REL = Path(
    "meta-avocado-nvidia/recipes-avocado/sdk/avocado-sdk-target/avocado-tegra-bootimg"
)
HELPER_SHEBANG = "#!/bin/sh"
TOOLS_DIRNAME = "tegraflash-tools"
HOST_TOOLS = ("python3", "fdtget", "fdtput", "cpp", "lsusb")
MIN_PYTHON = (3, 10)
VERSION_PROBE_TIMEOUT = 10


def _is_executable_file(path: Path) -> bool:
    return path.is_file() and os.access(path, os.X_OK)


def _lookup(template, *keys):
    node = template
    for key in keys:
        if not isinstance(node, dict) or key not in node:
            return None
        node = node[key]
    return node if isinstance(node, str) else None


def script_name(template, profile: str = PROFILE) -> str | None:
    return _lookup(template, "provision", "profiles", profile, "script")


def tools_dir_name(template) -> str | None:
    return image_entries(template).get("tegraflash_tools")


def check_executables(images_dir, template, profile: str = PROFILE) -> list[Problem]:
    images_dir = Path(images_dir)
    problems: list[Problem] = []

    name = script_name(template, profile)
    if name is None:
        problems.append(
            Problem(
                f"the manifest template names no provisioning script "
                f"(provision.profiles.{profile}.script is missing)",
                "avocado-stone",
            )
        )
    elif not _is_executable_file(images_dir / name):
        problems.append(
            Problem(
                f"the provisioning script {name} is missing or not "
                f"executable in {images_dir}",
                "avocado-stone",
            )
        )

    tools_name = tools_dir_name(template)
    if tools_name is None:
        problems.append(
            Problem(
                "the manifest template names no tegraflash tools directory "
                "(storage_devices.rootdisk.images.tegraflash_tools is missing)",
                "avocado-stone",
            )
        )
    else:
        initrd_flash = images_dir / tools_name / "initrd-flash"
        if not _is_executable_file(initrd_flash):
            problems.append(
                Problem(
                    f"{initrd_flash} is missing or not executable",
                    "tegraflash-tools-deploy",
                )
            )

    kernel = images_dir / "Image"
    if not kernel.is_file() or kernel.stat().st_size == 0:
        problems.append(
            Problem(
                f"the kernel image {kernel} is missing or empty, so the boot "
                "image could not pin the rootfs"
            )
        )
    return problems


# The provisioning script reads external-flash.xml.in (it copies the BSP into
# its build directory and applies that file), so it is the layout that counts;
# external-flash.xml is only a fallback when the .in file is absent.
LAYOUT_NAMES = ("external-flash.xml.in", "external-flash.xml")
# manifest image key -> partition name in the deployed layout. Only pairs
# whose partition is visible in the real external-flash.xml are listed.
FIT_PAIRS = (("rootfs", "APP"), ("tegraflash_esp", "esp"))
MAX_LAYOUT_BYTES = 4 * 1024 * 1024
# Decimal is capped at 31 digits so int() never meets its 4300-digit limit; a longer size is no partition size anyway.
_SIZE = re.compile(r"0[xX][0-9a-fA-F]+|[1-9][0-9]{0,30}|0")
_PLAIN_ENCODINGS = ("utf-8", "us-ascii")
_ENCODING_DECL = re.compile(
    r"""^\s*<\?xml[^>]*?\sencoding\s*=\s*["']([^"']*)["']""", re.IGNORECASE
)


class _Duplicate:
    """Marks a partition name listed more than once in a layout."""


DUPLICATE = _Duplicate()


def _plain_text(data: bytes) -> tuple[str | None, str | None]:
    """Return the layout as text, or a reason it is not plain UTF-8/ASCII.

    An entity declaration is found by searching the text, which only works if
    the bytes are what the XML parser will read: a UTF-16 or UTF-32 document
    hides ``<!DOCTYPE`` from a byte search, so those are refused outright.
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

    A name listed more than once maps to ``DUPLICATE``: its size is ambiguous.
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
        # int(raw, 0) alone also takes `1_0`, `+5` and `0b11`; the engine's fit check reads only decimal and 0x hex.
        sizes[name] = int(raw, 0) if _SIZE.fullmatch(raw) else raw
    return sizes, None


def _describe_size(value) -> str:
    return "it is listed more than once" if value is DUPLICATE else repr(value)


def _disagreements(primary: dict, other: dict) -> list[str]:
    return [
        part
        for _key, part in FIT_PAIRS
        if part in primary and part in other and primary[part] != other[part]
    ]


def fit_report(images_dir, template, entries) -> tuple[list[Problem], list[str]]:
    """Compare each image with its partition; return problems and summary lines.

    The layout is the safety net before an erase, so an absent, unparseable
    or non-numeric answer refuses instead of passing unchecked.
    """
    images_dir = Path(images_dir)
    bsp_dir = images_dir / entries.get("tegraflash_bsp", "tegraflash-bsp")
    target = BUILD_TARGETS["tegraflash_bsp"]
    found = [bsp_dir / n for n in LAYOUT_NAMES if (bsp_dir / n).is_file()]
    if not found:
        return [
            Problem(
                f"the partition fit cannot be verified: none of {', '.join(LAYOUT_NAMES)} in {bsp_dir}",
                target,
            )
        ], []
    layout = found[0]
    sizes, error = parse_partition_sizes(layout)
    if error is not None:
        return [Problem(f"the partition fit cannot be verified: {layout} is unreadable ({error})", target)], []

    problems: list[Problem] = []
    lines: list[str] = []
    if len(found) > 1:
        other_sizes, other_error = parse_partition_sizes(found[1])
        if other_error is None:
            for part in _disagreements(sizes, other_sizes):
                problems.append(
                    Problem(
                        f"the layouts disagree on partition {part}: {layout.name} says "
                        f"{_describe_size(sizes[part])} but {found[1].name} says {_describe_size(other_sizes[part])}; "
                        f"the provisioning script applies {layout.name}",
                        target,
                    )
                )
    for _key, part in FIT_PAIRS:
        if sizes.get(part) is DUPLICATE:
            problems.append(
                Problem(
                    f"partition {part} is listed more than once in {layout}, so its size is ambiguous",
                    target,
                )
            )
    for key, part in FIT_PAIRS:
        name = entries.get(key)
        if name is None or not (images_dir / name).is_file():
            continue  # a missing image is reported by check_images
        if sizes.get(part) is DUPLICATE:
            continue  # reported above
        if part not in sizes:
            problems.append(
                Problem(f"partition {part} is absent from the deployed layout {layout}, so {key} {name} cannot be checked", target)
            )
            continue
        size = sizes[part]
        if not isinstance(size, int):
            problems.append(
                Problem(f"the size of partition {part} in {layout} is {size!r}, not a number, so the fit of {key} {name} cannot be verified", target)
            )
            continue
        image_size = os.stat(images_dir / name).st_size
        if image_size > size:
            hint = "; rebuild with a larger ROOTFSPART_SIZE_DEFAULT" if key == "rootfs" else ""
            problems.append(
                Problem(
                    f"{key} image {name} ({image_size} bytes) does not fit partition {part} ({size} bytes) in the deployed layout{hint}",
                    target,
                )
            )
        else:
            lines.append(f"fit: {key} {image_size} <= {part} {size}")
    return problems, lines


def check_partition_fit(images_dir, template, entries) -> list[Problem]:
    return fit_report(images_dir, template, entries)[0]


def find_bootimg_helper(layer_root) -> Path | None:
    """The helper is committed mode 100644, so only the shebang is checked."""
    helper = Path(layer_root) / HELPER_REL
    if not helper.is_file():
        return None
    try:
        with helper.open("r", encoding="utf-8", errors="replace") as fh:
            first = fh.readline().rstrip("\r\n")
    except OSError:
        return None
    return helper if first == HELPER_SHEBANG else None


def helper_problem(helper) -> Problem | None:
    if helper is not None:
        return None
    return Problem(
        "avocado-tegra-bootimg was not found, so the flash would boot an image "
        "that does not name its rootfs"
    )


def check_mkbootimg(images_dir, path=None, tools_dirname=TOOLS_DIRNAME) -> tuple[list[Problem], Path | None]:
    """Return problems and the directory to prepend to PATH, if one is needed."""
    if shutil.which("mkbootimg", path=path):
        return [], None
    tools_dir = Path(images_dir) / tools_dirname
    if _is_executable_file(tools_dir / "mkbootimg"):
        return [], tools_dir
    return (
        [
            Problem(
                "mkbootimg is neither executable under "
                f"{tools_dir} nor on the search path; the boot image helper "
                "refuses a non-executable mkbootimg"
            )
        ],
        None,
    )


def python_version(python3) -> tuple[int, int] | None:
    """The (major, minor) of the given interpreter, or None when it cannot say."""
    code = "import sys; print('%d.%d' % sys.version_info[:2])"
    with tempfile.TemporaryFile() as out:
        try:
            done = subprocess.run(
                [os.fspath(python3), "-I", "-c", code],
                stdin=subprocess.DEVNULL,
                stdout=out,
                stderr=subprocess.DEVNULL,
                timeout=VERSION_PROBE_TIMEOUT,
                start_new_session=True,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        if done.returncode != 0:
            return None
        out.seek(0)
        text = out.read().decode("ascii", errors="replace").strip()
    match = re.fullmatch(r"(\d+)\.(\d+)", text)
    return (int(match.group(1)), int(match.group(2))) if match else None


def _version_text(version) -> str:
    return ".".join(str(part) for part in version)


def check_host_tools(path=None, version_of=None) -> list[Problem]:
    """Check every host tool, and that the python3 found is new enough.

    The version is read from the python3 on ``path`` (the one the provisioning
    shim will run), not from the interpreter running this tool.
    """
    version_of = version_of or python_version  # looked up late so tests can swap the probe
    problems: list[Problem] = []
    python3 = None
    for tool in HOST_TOOLS:
        found = shutil.which(tool, path=path)
        if found is None:
            problems.append(Problem(f"host tool {tool} is not on the search path"))
        elif tool == "python3":
            python3 = found
    if python3 is not None:
        version = version_of(python3)
        needed = _version_text(MIN_PYTHON)
        if version is None:
            problems.append(
                Problem(f"the version of {python3} could not be read; python3 {needed} or newer is needed")
            )
        elif tuple(version) < MIN_PYTHON:
            problems.append(
                Problem(f"python3 {_version_text(version)} found at {python3}; python3 {needed} or newer is needed")
            )
    return problems
