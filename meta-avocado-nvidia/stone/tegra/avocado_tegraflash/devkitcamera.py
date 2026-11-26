"""Strip the devkit reference-camera fragments when a carrier device tree is in use.

The stock dynamic overlay carries camera fragments that reset integrator-set
camera properties on a carrier board. The strip works on the work directory's
copy only, proves no kept fragment points into a removed one, and refuses
otherwise: a malformed overlay in the bootloader costs a recovery-mode reflash.
"""

import os
import struct
from pathlib import Path

from . import EngineError
from .bootoverlays import _ASSIGN, PLUGIN_MANAGER, CarrierShape, EffectiveView, OverlayLists
from .fdtreplay import Tree, read_tree
from .files import read_text_preserving, write_text_replacing_link

CAMERA_FRAGMENT_PREFIX = "fragment-camera"
CAMERA_OVERLAY_MARKER = "-camera-"
DYNAMIC_SUFFIX = "-dynamic.dtbo"
REQUIRED_OVERLAYS = ("tegra234-carveouts.dtbo", "tegra-optee.dtbo")
# One edit of a local overlay file; the bound only stops a wedged tool from hanging the engine.
TOOL_TIMEOUT = 60.0
_PHANDLE_PROPS = ("phandle", "linux,phandle")
_SYMBOLS = "/__symbols__"
_FIXUPS = "/__fixups__"
_LOCAL_FIXUPS = "/__local_fixups__"
_PREFIX = "devkit camera fragments: "


def _inside(path: str, fragment: str) -> bool:
    return path == fragment or path.startswith(fragment + "/")


def _fragment_of(path: str) -> str:
    return "/" + path.strip("/").split("/", 1)[0]


def _strings(value: bytes) -> list[str]:
    return [s.decode(errors="replace") for s in value.split(b"\x00") if s]


def _phandle_owners(tree: Tree) -> dict[int, str]:
    owners: dict[int, str] = {}
    for node, props in tree.items():
        for name in _PHANDLE_PROPS:
            if len(props.get(name, b"")) == 4:
                owners[struct.unpack(">I", props[name])[0]] = node
    return owners


def _check_references(tree: Tree, removed: list[str], dynamic: str) -> None:
    """Refuse when a kept fragment holds a phandle of, or a fixup label for, a removed node."""
    owners = _phandle_owners(tree)

    def removed_of(path: str) -> str | None:
        return next((f for f in removed if _inside(path, f)), None)

    for node, props in tree.items():
        if not node.startswith(_LOCAL_FIXUPS + "/"):
            continue
        target = node[len(_LOCAL_FIXUPS) :]
        if removed_of(target):
            continue
        for prop, offsets in props.items():
            value = tree.get(target, {}).get(prop, b"")
            for (offset,) in struct.iter_unpack(">I", offsets[: len(offsets) // 4 * 4]):
                cell = value[offset : offset + 4]
                hit = owners.get(struct.unpack(">I", cell)[0]) if len(cell) == 4 else None
                if hit and removed_of(hit):
                    raise EngineError(
                        f"{dynamic}: kept fragment {_fragment_of(target)} property {prop} of {target} holds a "
                        f"phandle of node {hit} inside the removed fragment {removed_of(hit)}"
                    )

    symbols = {name: _strings(value) for name, value in tree.get(_SYMBOLS, {}).items()}
    for label, value in tree.get(_FIXUPS, {}).items():
        resolved = symbols.get(label, [""])[0]
        gone = removed_of(resolved) if resolved else None
        if not gone:
            continue
        for entry in _strings(value):
            path, _, rest = entry.partition(":")
            if not removed_of(path):
                raise EngineError(
                    f"{dynamic}: kept fragment {_fragment_of(path)} property {rest.split(':')[0]} of {path} "
                    f"refers through label {label} to node {resolved} inside the removed fragment {gone}"
                )


def _tool(runner, argv: list[str], what: str) -> None:
    status, output = runner.capture(argv, timeout=TOOL_TIMEOUT)
    if status != 0:
        raise EngineError(f"{what} failed (status {status}): {output.strip()}")


def _strip_overlay(path: Path, tree: Tree, removed: list[str], runner) -> None:
    """Edit a scratch copy and rename it over `path`, so a failure leaves the original and a link is replaced."""
    scratch = path.with_name(f".{path.name}.{os.urandom(6).hex()}.strip")
    try:
        scratch.write_bytes(path.read_bytes())
        names = [f.lstrip("/") for f in removed]
        nodes = [f for f in removed] + [f"{_LOCAL_FIXUPS}/{n}" for n in names if f"{_LOCAL_FIXUPS}/{n}" in tree]
        _tool(runner, ["fdtput", "-r", str(scratch), *nodes], "removing the camera fragments")

        dead = [p for p, v in tree.get(_SYMBOLS, {}).items() if any(_inside(s, f) for s in _strings(v) for f in removed)]
        if dead:
            _tool(runner, ["fdtput", "-d", str(scratch), _SYMBOLS, *dead], "removing the camera symbols")

        for label, value in tree.get(_FIXUPS, {}).items():
            kept = [e for e in _strings(value) if not any(_inside(e.partition(":")[0], f) for f in removed)]
            if len(kept) == len(_strings(value)):
                continue
            if not kept:
                _tool(runner, ["fdtput", "-d", str(scratch), _FIXUPS, label], "removing a camera fixup")
                continue
            raw = b"".join(e.encode() + b"\x00" for e in kept)
            _tool(
                runner,
                ["fdtput", "-t", "bx", str(scratch), _FIXUPS, label, *(f"{b:02x}" for b in raw)],
                "rewriting a camera fixup",
            )
        read_tree(scratch)
        os.replace(scratch, path)
    except OSError as exc:
        raise EngineError(f"cannot strip the camera fragments from {path}: {exc}") from exc
    finally:
        if os.path.lexists(scratch):
            scratch.unlink()


def _rewrite_plugin_assignments(path: str, text: str) -> str:
    out = []
    for line in text.split("\n"):
        match = _ASSIGN.fullmatch(line)
        if match and match["name"] == PLUGIN_MANAGER:
            value = next(g for g in (match["dq"], match["sq"], match["bare"]) if g is not None)
            kept = ",".join(e for e in value.split(",") if e and CAMERA_OVERLAY_MARKER not in e)
            prefix = "export " if line.startswith("export ") else ""
            line = f'{prefix}{PLUGIN_MANAGER}="{kept}"'
        out.append(line)
    return "\n".join(out)


def apply_policy(
    view: EffectiveView,
    lists: OverlayLists,
    carrier_tree: CarrierShape,
    carrier_list_set: bool,
    runner,
    log,
) -> bool:
    """Strip the devkit camera fragments from the work directory when a carrier tree is in use.

    Returns whether the dynamic overlay or the working flashvars was modified.
    Raises EngineError, before changing either file, when the strip cannot be
    proven safe.
    """
    if carrier_tree is CarrierShape.NONE:
        log(_PREFIX + "no carrier device tree in use; left unchanged")
        return False
    if carrier_list_set:
        log(
            _PREFIX + "the carrier sets its own PLUGIN_MANAGER_OVERLAYS; "
            "its list and the stock dynamic overlay are used unchanged"
        )
        return False

    original = list(lists.plugin_manager or ())
    trimmed = [e for e in original if CAMERA_OVERLAY_MARKER not in e]
    dynamic = next((e for e in original if e.endswith(DYNAMIC_SUFFIX)), None)
    for name in (dynamic, *REQUIRED_OVERLAYS):
        if name in original and name not in trimmed:
            raise EngineError(f"{PLUGIN_MANAGER}: dropping the camera overlays would also drop {name}")

    removed: list[str] = []
    tree: Tree = {}
    overlay_path = None
    if dynamic is not None:
        resolved = view.resolve(dynamic)
        if resolved is None or not os.path.isfile(resolved):
            raise EngineError(f"{dynamic}: dynamic overlay listed in {PLUGIN_MANAGER} is not in the work directory")
        overlay_path = Path(resolved)
        tree = read_tree(overlay_path)
        removed = sorted(
            n for n in tree if n.count("/") == 1 and n.lstrip("/").startswith(CAMERA_FRAGMENT_PREFIX)
        )
        if removed:
            _check_references(tree, removed, dynamic)
        else:
            log(_PREFIX + f"none found in {dynamic}; overlay left unchanged")

    if removed:
        _strip_overlay(overlay_path, tree, removed, runner)
        for fragment in removed:
            log(_PREFIX + f"removed {fragment.lstrip('/')} from {dynamic} (carrier device tree in use)")

    if trimmed != original:
        flashvars = view.resolve("flashvars")
        text = read_text_preserving(flashvars)
        write_text_replacing_link(
            flashvars,
            _rewrite_plugin_assignments(flashvars, text),
            encoding="utf-8",
            errors="surrogateescape",
            newline="",
        )
        for entry in original:
            if entry not in trimmed:
                log(_PREFIX + f"dropped {entry} from {PLUGIN_MANAGER} (carrier device tree in use)")
    return bool(removed) or trimmed != original
