"""Boot overlay lists: read them as the flash helper will, compose the chain, detect carrier trees.

The flash helper sources flashvars with bash, so the value that matters is bash's.
This module reads only the assignment forms it can read exactly and refuses every
other use of the three list names, never executing the file.
"""

import os
import re
from dataclasses import dataclass
from enum import Enum

from . import EngineError
from .carrier import carrier_patches
from .files import read_text_preserving

BOOTCONTROL = "BOOTCONTROL_OVERLAYS"
PLUGIN_MANAGER = "PLUGIN_MANAGER_OVERLAYS"
EXTRA = "OVERLAY_DTB_FILE"
_NAMES = (BOOTCONTROL, PLUGIN_MANAGER, EXTRA)

_ASSIGN = re.compile(
    r"(?:export )?(?P<name>" + "|".join(_NAMES) + r")="
    r"(?:\"(?P<dq>[^\"$`\\]*)\"|'(?P<sq>[^'$`\\]*)'|(?P<bare>[^\s\"'$`\\;&|<>()#]*))"
    r"[ \t]*"
)
_MENTION = {n: re.compile(r"(?<![A-Za-z0-9_])" + n + r"(?![A-Za-z0-9_])") for n in _NAMES}
_REDIRECT_NAME = "DTBFILE"
_ENV_TARGET = ".env.initrd-flash"


@dataclass(frozen=True)
class OverlayLists:
    """Each list is a tuple of file names, or None when the name is never assigned."""

    bootcontrol: tuple[str, ...] | None
    plugin_manager: tuple[str, ...] | None
    extra: tuple[str, ...] | None


class CarrierShape(Enum):
    NONE = "none"
    A = "A"
    B = "B"
    BOTH = "both"


def _split(value: str) -> tuple[str, ...]:
    return tuple(item for item in value.split(",") if item)


def parse_overlay_lists(text: str, source: str) -> OverlayLists:
    """Read the three lists from flashvars text; `source` names the file in refusals."""
    found: dict[str, tuple[str, ...]] = {}
    for number, line in enumerate(text.split("\n"), start=1):
        if line.lstrip().startswith("#"):
            continue
        match = _ASSIGN.fullmatch(line)
        if match:
            value = next(g for g in (match["dq"], match["sq"], match["bare"]) if g is not None)
            found[match["name"]] = _split(value)
            continue
        for name in _NAMES:
            if _MENTION[name].search(line):
                raise EngineError(
                    f"{source}: line {number} uses {name} in a form the engine will not interpret "
                    f"(only NAME=value, NAME=\"value\" or NAME='value' at column 0, optionally "
                    f"after `export `, without $ or backticks): {line.strip()!r}"
                )
    return OverlayLists(found.get(BOOTCONTROL), found.get(PLUGIN_MANAGER), found.get(EXTRA))


def read_overlay_lists(path: str) -> OverlayLists:
    return parse_overlay_lists(read_text_preserving(path), path)


def overlay_chain(lists: OverlayLists) -> list[str]:
    """The order the flash helper composes: bootcontrol, plugin-manager, then OVERLAY_DTB_FILE.

    An empty plugin-manager list drops out, leaving the extra list right after
    bootcontrol, as the helper builds it.
    """
    return [*(lists.bootcontrol or ()), *(lists.plugin_manager or ()), *(lists.extra or ())]


def format_lists(lists: OverlayLists) -> list[str]:
    lines = ["UEFI applies these boot overlays at every boot, in this order:"]
    for name, value in zip(_NAMES, (lists.bootcontrol, lists.plugin_manager, lists.extra)):
        lines.append(f"  {name}: {','.join(value) if value else '<unset>'}")
    return lines


def _patch_flashvars(text: str, patches: list[tuple[str, str, str]]) -> str:
    """Apply CARRIER_FV_ patches in memory with the carrier overlay's rewrite rule."""
    lines = text.split("\n")
    for target, name, value in patches:
        if target != "flashvars":
            continue
        prefix = name + "="
        lines = [f'{name}="{value}"' if line.startswith(prefix) else line for line in lines]
    return "\n".join(lines)


class EffectiveView:
    """What the flash will see: the work directory itself, or the carrier slot laid over the BSP.

    Layered mode lets the build-time check predict provisioning without copying the BSP.
    """

    def __init__(self, work: str | None, bsp: str | None, carrier_dir: str | None, patches):
        self._work = work
        self._bsp = bsp
        self._carrier_dir = carrier_dir
        self._patches = list(patches)

    @classmethod
    def work_dir(cls, work: str) -> "EffectiveView":
        return cls(work, None, None, [])

    @classmethod
    def layered(cls, bsp: str, carrier_dir: str, patches: list[tuple[str, str, str]]) -> "EffectiveView":
        return cls(None, bsp, carrier_dir, patches)

    def resolve(self, name: str) -> str | None:
        """Path of `name` in this view, or None when it exists nowhere in it."""
        if self._work is not None:
            return os.path.join(self._work, name)
        for root in (self._carrier_dir, self._bsp):
            candidate = os.path.join(root, name)
            if os.path.exists(candidate):
                return candidate
        return None

    def flashvars_text(self) -> str:
        path = self.resolve("flashvars")
        if path is None or not os.path.isfile(path):
            raise EngineError("flashvars not found in the BSP or the carrier slot")
        text = read_text_preserving(path)
        return text if self._work is not None else _patch_flashvars(text, self._patches)

    def overlay_lists(self) -> OverlayLists:
        return parse_overlay_lists(self.flashvars_text(), "flashvars")


def carrier_redirect(env_text: str, base_name: str) -> str | None:
    """The tree the last column-0 CARRIER_ENV_DTBFILE selects, None when absent or the base tree itself."""
    value = None
    for target, name, val in carrier_patches(env_text, validate=False):
        if target == _ENV_TARGET and name == _REDIRECT_NAME:
            value = val
    if not value or os.path.basename(value) == base_name:
        return None
    return value


def detect_carrier_tree(carrier_dir: str, base_name: str, env_text: str) -> CarrierShape:
    """A: the slot ships `base_name`. B: the carrier env redirects to another tree. Both, or none."""
    shape_a = os.path.lexists(os.path.join(carrier_dir, base_name))
    shape_b = carrier_redirect(env_text, base_name) is not None
    if shape_a and shape_b:
        return CarrierShape.BOTH
    if shape_a:
        return CarrierShape.A
    return CarrierShape.B if shape_b else CarrierShape.NONE


def carrier_sets_plugin_list(patches: list[tuple[str, str, str]]) -> bool:
    return any(target == "flashvars" and name == PLUGIN_MANAGER for target, name, _ in patches)
