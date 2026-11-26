"""Build-time boot overlay check: the provisioning stage, run on scratch copies of what it reads.

Provisioning refuses a bad overlay only after the images are staged and the board
is waiting; the same stage run at `avocado build` shows the lists and the camera
policy while the integrator can still change the carrier slot. It runs the engine's
own stage rather than a second implementation so the two cannot drift.
"""

import argparse
import os
import shutil
import sys
import tempfile
from pathlib import Path

from . import EngineError
from .bootoverlays import EffectiveView, overlay_chain
from .bootstage import stage
from .carrier import _selected_tree, carrier_patches
from .fdtreplay import read_tree
from .files import join_name, read_text_preserving
from .fit import DUPLICATE, _parse_layout
from .manifest import read_manifest, read_ota_image
from .runner import SubprocessRunner
from .settings import EMMC_LAYOUT, EXTERNAL_LAYOUT

_ENV_FILE = ".env.initrd-flash"
_NOT_VISIBLE = (
    "A tree merged from declared overlays is not visible at build time; "
    "it is checked at provision."
)
_TOOLS = ("fdtoverlay", "fdtput")
_OTA_PARTITION = "A_kernel-dtb"
_OTA_NOTE = (
    "The OS update replaces the kernel device tree only; the boot overlay lists in the bootloader "
    "stay as last flashed, so a change to them or to the CARRIER_FV knobs needs a reflash."
)


def _resolve_dir(name: str, roots: list[str]) -> Path | None:
    """First root holding the directory `name`, in stone's order."""
    for root in roots:
        candidate = join_name(root, name)
        if candidate.is_dir():
            return candidate
    return None


def _patched_env(text: str, patches: list[tuple[str, str, str]]) -> str:
    """Apply CARRIER_ENV_ patches in memory with the carrier overlay's rewrite rule."""
    lines = text.split("\n")
    for target, name, value in patches:
        if target != _ENV_FILE:
            continue
        lines = [f'{name}="{value}"' if line.startswith(name + "=") else line for line in lines]
    return "\n".join(lines)


def _copy(view: EffectiveView, name: str, dest: Path) -> bool:
    """Copy `name` from the view to `dest` as a regular file; False when the view has none."""
    if ".." in Path(name).parts:
        raise EngineError(f"{name}: names a path outside the BSP; refusing to read it")
    source = view.resolve(name)
    if source is None or not os.path.isfile(source):
        return False
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, dest)
    return True


def _scratch(scratch: Path, bsp: Path, carrier: Path | None) -> tuple[EffectiveView, Path | None, Path | None]:
    """Copy only what the stage reads into `scratch`; return its view and the two tree paths."""
    carrier_env = carrier / "carrier.env" if carrier else None
    env_text = read_text_preserving(carrier_env) if carrier_env and carrier_env.is_file() else ""
    patches = carrier_patches(env_text)
    layered = EffectiveView.layered(str(bsp), str(carrier), patches) if carrier else EffectiveView.work_dir(str(bsp))

    flashvars = layered.resolve("flashvars")
    if flashvars is not None and os.path.isfile(flashvars):
        (scratch / "flashvars").write_text(layered.flashvars_text(), encoding="utf-8", errors="surrogateescape")
        lists = layered.overlay_lists()
        for name in overlay_chain(lists):
            _copy(layered, name, scratch / name)

    env_path = layered.resolve(_ENV_FILE)
    if env_path is not None and os.path.isfile(env_path):
        (scratch / _ENV_FILE).write_text(
            _patched_env(read_text_preserving(env_path), patches), encoding="utf-8", errors="surrogateescape"
        )

    stock_name = _selected_tree(str(bsp))
    flashed_name = _selected_tree(str(scratch))
    stock = scratch / ".stock" / stock_name if stock_name else None
    if stock is not None and not _copy(EffectiveView.work_dir(str(bsp)), stock_name, stock):
        stock = None
    flashed = scratch / flashed_name if flashed_name else None
    if flashed is not None and not _copy(layered, flashed_name, flashed):
        flashed = None
    return EffectiveView.work_dir(str(scratch)), stock, flashed


def _partition_size(bsp: Path) -> int:
    """The A_kernel-dtb size both flash layouts the BSP ships agree on.

    The build does not know which profile will provision, so either layout may be
    the one flashed and a disagreement leaves no limit that is true for both.
    """
    sizes = {}
    for name in (EXTERNAL_LAYOUT, EMMC_LAYOUT):
        path = bsp / name
        if not path.is_file():
            continue
        layout = _parse_layout(path)
        if layout.error is not None:
            raise EngineError(f"{path}: cannot read the flash layout ({layout.error})")
        size = layout.sizes.get(_OTA_PARTITION)
        if size is None or size is DUPLICATE or not isinstance(size, int):
            raise EngineError(f"{path}: partition {_OTA_PARTITION} has no usable size (found {size!r})")
        sizes[name] = size
    if not sizes:
        raise EngineError(f"{bsp}: no flash layout ({EXTERNAL_LAYOUT} or {EMMC_LAYOUT}) to read the {_OTA_PARTITION} size from")
    if len(set(sizes.values())) > 1:
        detail = ", ".join(f"{name} {size}" for name, size in sizes.items())
        raise EngineError(f"the flash layouts disagree on the {_OTA_PARTITION} size ({detail}); no single limit applies")
    return next(iter(sizes.values()))


def _publish(name: str, tree: Path, partition: int, input_dir: Path) -> None:
    """Validate `tree`, then replace <input dir>/`name` with it atomically."""
    size = tree.stat().st_size
    where = f"{tree.name} ({size} bytes, {_OTA_PARTITION} is {partition} bytes)"
    try:
        read_tree(tree)
    except EngineError as exc:
        raise EngineError(f"{where}: not a valid device tree: {exc}") from exc
    if size > partition:
        raise EngineError(f"{where}: larger than the {_OTA_PARTITION} partition; refusing to publish it")
    fd, tmp = tempfile.mkstemp(prefix=f".{name}.", dir=input_dir)
    try:
        with os.fdopen(fd, "wb") as out, open(tree, "rb") as src:
            shutil.copyfileobj(src, out)
        os.chmod(tmp, 0o644)
        os.replace(tmp, input_dir / name)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def _skip(args: argparse.Namespace, log, reason: str) -> int:
    """Skip the check with a warning, or fail when the manifest declares the update tree.

    With the tree declared, a skip would leave `stone bundle` to fail on a missing
    file, or to pack a copy an earlier build left behind.
    """
    if read_ota_image(args.manifest_file):
        raise EngineError(f"{reason}, and the manifest declares the device-tree update image that this check writes")
    log(f"WARNING: {reason}; the boot overlay check is skipped")
    return 0


def check(args: argparse.Namespace, log=print) -> int:
    """Run the check; return the process exit status."""
    missing = [tool for tool in _TOOLS if shutil.which(tool) is None]
    if missing:
        return _skip(args, log, f"{' and '.join(missing)} not found")

    roots = [r for r in args.include_paths.split(":") if r] + [args.input_dir]
    if args.sdk_stone_dir:
        roots.append(args.sdk_stone_dir)
    man = read_manifest(args.manifest_file)
    bsp = _resolve_dir(man.tegraflash_bsp, roots) if man.tegraflash_bsp else None
    if bsp is None:
        return _skip(args, log, "the BSP directory named by the manifest was not found")
    carrier = None
    if man.tegraflash_carrier_bsp:
        carrier = _resolve_dir(man.tegraflash_carrier_bsp, roots)
        if carrier is None:
            return _skip(args, log, f"the carrier slot {man.tegraflash_carrier_bsp} was not found")

    with tempfile.TemporaryDirectory(prefix="avocado-buildcheck-") as tmp:
        view, stock, flashed = _scratch(Path(tmp), bsp, carrier)
        ota_name = read_ota_image(args.manifest_file)
        snapshot = None
        if ota_name:
            # Taken before the stage so the update carries the tree provisioning starts from, whatever the stage does to its copies.
            tree = flashed or stock
            if tree is None:
                raise EngineError("no device tree to publish: neither the carrier nor the BSP provides the selected tree")
            snapshot = Path(tmp) / ".ota" / tree.name
            snapshot.parent.mkdir()
            shutil.copyfile(tree, snapshot)
        summary = stage(
            view,
            stock,
            flashed,
            SubprocessRunner(),
            log,
            carrier_dir=str(carrier) if carrier else None,
            base_tree_name=os.path.basename(_selected_tree(str(bsp))),
        )
        if snapshot is not None:
            _publish(ota_name, snapshot, _partition_size(bsp), Path(args.input_dir))
    log(summary)
    log(_NOT_VISIBLE)
    if snapshot is not None:
        log(_OTA_NOTE)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="avocado_tegraflash.buildcheck", description=__doc__)
    parser.add_argument("--input-dir", required=True)
    # Not dest="manifest": tests/test_manifest_contract.py allows a `.manifest` attribute only in cli.py.
    parser.add_argument("--manifest", dest="manifest_file", required=True)
    parser.add_argument("--include-paths", default="", help="colon-separated directories searched before the input dir")
    parser.add_argument("--sdk-stone-dir", default="")
    args = parser.parse_args(argv)
    try:
        return check(args)
    except EngineError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
