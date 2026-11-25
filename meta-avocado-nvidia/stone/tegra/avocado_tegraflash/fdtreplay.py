"""Replay the boot overlay chain onto a flashed device tree and report integrator-set changes."""

import shutil
import struct
from dataclasses import dataclass, field
from pathlib import Path

from . import EngineError
from .runner import Runner

FDT_MAGIC = 0xD00DFEED
BEGIN_NODE, END_NODE, PROP, NOP, END = 1, 2, 3, 4, 9
# Overlay bookkeeping the tools rewrite on every apply; never an integrator choice.
IGNORED_NODES = ("/__symbols__", "/__fixups__", "/__local_fixups__")
# One overlay apply is a local file merge; the bound only stops a wedged tool from hanging the engine.
FDTOVERLAY_TIMEOUT = 60.0

Tree = dict[str, dict[str, bytes]]
PropKey = tuple[str, str]


@dataclass(frozen=True)
class PropertyChange:
    path: str
    property: str
    before: str | None
    after: str | None
    overlay: str


@dataclass(frozen=True)
class OverlayFailure:
    overlay: str
    status: int
    output: str


@dataclass
class ReplayResult:
    changes: list[PropertyChange] = field(default_factory=list)
    failures: list[OverlayFailure] = field(default_factory=list)
    applied: list[str] = field(default_factory=list)
    no_integrator_properties: bool = False
    skipped: str | None = None


def _bad(path: Path, why: str) -> EngineError:
    return EngineError(f"{path}: not a valid device tree ({why})")


def read_tree(path: str | Path) -> Tree:
    """Parse a flattened device tree into {node path: {property: value bytes}}."""
    path = Path(path)
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise EngineError(f"{path}: cannot read device tree: {exc.strerror or exc}") from exc
    if len(data) < 40:
        raise _bad(path, "shorter than the header")
    magic, total, off_struct, off_strings, _rsvmap, _ver, _compat, _cpu, size_strings, size_struct = struct.unpack(
        ">10I", data[:40]
    )
    if magic != FDT_MAGIC:
        raise _bad(path, "bad magic")
    if total > len(data) or off_struct + size_struct > total or off_strings + size_strings > total:
        raise _bad(path, "blocks extend past the end of the file")
    strings = data[off_strings : off_strings + size_strings]
    block = data[off_struct : off_struct + size_struct]

    def name_at(offset: int) -> str:
        end = strings.find(b"\x00", offset)
        if offset >= len(strings) or end < 0:
            raise _bad(path, "property name outside the strings block")
        return strings[offset:end].decode(errors="replace")

    tree: Tree = {}
    stack: list[str] = []
    pos = 0
    while True:
        if pos + 4 > len(block):
            raise _bad(path, "structure block ends before the END token")
        (token,) = struct.unpack_from(">I", block, pos)
        pos += 4
        if token == BEGIN_NODE:
            end = block.find(b"\x00", pos)
            if end < 0:
                raise _bad(path, "unterminated node name")
            name = block[pos:end].decode(errors="replace")
            pos = (end + 1 + 3) & ~3
            if not stack:
                node = "/"
            else:
                node = (stack[-1].rstrip("/") + "/" + name)
            stack.append(node)
            tree.setdefault(node, {})
        elif token == END_NODE:
            if not stack:
                raise _bad(path, "END_NODE without a node")
            stack.pop()
        elif token == PROP:
            if not stack or pos + 8 > len(block):
                raise _bad(path, "property outside a node or truncated")
            length, nameoff = struct.unpack_from(">II", block, pos)
            pos += 8
            if pos + length > len(block):
                raise _bad(path, "property value past the structure block")
            tree[stack[-1]][name_at(nameoff)] = bytes(block[pos : pos + length])
            pos = (pos + length + 3) & ~3
        elif token == NOP:
            continue
        elif token == END:
            if stack:
                raise _bad(path, "END with open nodes")
            if not tree:
                raise _bad(path, "no root node")
            return tree
        else:
            raise _bad(path, f"unknown token {token}")


def _ignored(node: str) -> bool:
    return any(node == n or node.startswith(n + "/") for n in IGNORED_NODES)


def integrator_set(stock: Tree, flashed: Tree) -> dict[PropKey, bytes]:
    """Properties of the flashed tree that the stock tree lacks or holds with another value."""
    out: dict[PropKey, bytes] = {}
    for node, props in flashed.items():
        if _ignored(node):
            continue
        base = stock.get(node, {})
        for name, value in props.items():
            if base.get(name) != value:
                out[(node, name)] = value
    return out


def format_value(value: bytes | None) -> str | None:
    if value is None:
        return None
    if value.endswith(b"\x00") and len(value) > 1:
        body = value[:-1]
        parts = body.split(b"\x00")
        if all(p and all(32 <= b < 127 for b in p) for p in parts):
            return ", ".join(p.decode() for p in parts)
    if value and len(value) % 4 == 0:
        return " ".join(f"0x{cell:08x}" for cell in struct.unpack(f">{len(value) // 4}I", value))
    return value.hex() or "<empty>"


def replay(
    flashed_path: str | Path,
    overlay_paths: list[str | Path],
    runner: Runner,
    scratch_dir: str | Path,
    *,
    stock_path: str | Path,
) -> ReplayResult:
    """Apply the overlays one at a time to scratch copies of the flashed tree.

    The input tree is never written. A property counts as integrator-set when
    the flashed tree differs from `stock_path`; each later change to one of
    them is recorded against the overlay that made it.
    """
    result = ReplayResult()
    flashed_path, stock_path = Path(flashed_path), Path(stock_path)
    if flashed_path.read_bytes() == stock_path.read_bytes():
        result.no_integrator_properties = True
        return result
    current = read_tree(flashed_path)
    watched = integrator_set(read_tree(stock_path), current)
    if shutil.which("fdtoverlay") is None:
        result.skipped = "fdtoverlay is not on PATH (device-tree-compiler package)"
        return result

    scratch = Path(scratch_dir)
    scratch.mkdir(parents=True, exist_ok=True)
    tree_file = scratch / "step-0.dtb"
    shutil.copyfile(flashed_path, tree_file)
    for index, overlay in enumerate(overlay_paths, start=1):
        overlay = Path(overlay)
        out_file = scratch / f"step-{index}.dtb"
        status, output = runner.capture(
            ["fdtoverlay", "-i", str(tree_file), "-o", str(out_file), str(overlay)],
            timeout=FDTOVERLAY_TIMEOUT,
        )
        if status != 0 or not out_file.exists():
            result.failures.append(OverlayFailure(overlay.name, status, output))
            continue
        try:
            nxt = read_tree(out_file)
        except EngineError as exc:
            result.failures.append(OverlayFailure(overlay.name, status, str(exc)))
            continue
        result.applied.append(overlay.name)
        for node, name in watched:
            before = current.get(node, {}).get(name)
            after = nxt.get(node, {}).get(name)
            if before != after:
                result.changes.append(
                    PropertyChange(node, name, format_value(before), format_value(after), overlay.name)
                )
        current, tree_file = nxt, out_file
    return result
