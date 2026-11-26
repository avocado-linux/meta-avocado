"""The boot overlay stage: show the lists, apply the camera policy, replay the chain.

It runs on the staged work directory before any board contact, so the integrator
sees what UEFI will apply at every boot while a bad overlay can still be refused.
"""

import os
import tempfile
from pathlib import Path

from . import EngineError
from .bootoverlays import (
    CarrierShape,
    EffectiveView,
    carrier_redirect,
    carrier_sets_plugin_list,
    detect_carrier_tree,
    format_lists,
    overlay_chain,
)
from .carrier import _selected_tree, carrier_patches
from .devkitcamera import apply_policy
from .fdtreplay import replay
from .files import join_name, read_text_preserving

SUMMARY_PREFIX = "Boot overlays at flash:"
_UNKNOWN = "unknown (the BSP has no flashvars)"


def _shape(carrier_dir: str | None, base_name: str, env_text: str) -> CarrierShape:
    if carrier_dir is None:
        return CarrierShape.NONE
    if not base_name:
        # Without a base tree name the slot cannot be asked whether it ships one.
        return CarrierShape.B if carrier_redirect(env_text, "") else CarrierShape.NONE
    return detect_carrier_tree(carrier_dir, base_name, env_text)


def _snapshot(view: EffectiveView, names: list[str]) -> dict[str, bytes | None]:
    out: dict[str, bytes | None] = {}
    for name in names:
        path = view.resolve(name)
        out[name] = Path(path).read_bytes() if path and os.path.isfile(path) else None
    return out


def _skip_reason(flashed: Path | None, stock: Path | None) -> str | None:
    if flashed is None:
        return "DTBFILE is not set"
    if stock is None:
        return "the BSP's own DTBFILE is not set, so there is no stock tree to compare with"
    for path in (flashed, stock):
        if not path.is_file():
            return f"{path} does not exist"
    return None


def _show(value: str | None) -> str:
    return "<absent>" if value is None else value


def stage(
    view: EffectiveView,
    stock_tree: Path | None,
    flashed_tree: Path | None,
    runner,
    log,
    *,
    carrier_dir: str | None = None,
    base_tree_name: str = "",
) -> str:
    """Run the stage on `view` and return a one-line summary.

    `flashed_tree` is the tree the flash writes (never the `kernel_`-prefixed
    copy, which the flash helper regenerates from it) and `stock_tree` the BSP's
    own copy of the tree it started from; either may be None or absent, which
    skips the replay. `carrier_dir` is the carrier slot and `base_tree_name` the
    BSP's own DTBFILE name, the two things that tell a carrier tree is in use.
    Raises EngineError when a list cannot be read, the camera strip cannot be
    proven safe, or an overlay the policy modified fails to apply.
    """
    flashvars = view.resolve("flashvars")
    if flashvars is None or not os.path.isfile(flashvars):
        log(f"UEFI applies these boot overlays at every boot: {_UNKNOWN}")
        return f"{SUMMARY_PREFIX} {_UNKNOWN}"

    lists = view.overlay_lists()
    for line in format_lists(lists):
        log(line)

    env_path = os.path.join(carrier_dir, "carrier.env") if carrier_dir else ""
    env_text = read_text_preserving(env_path) if env_path and os.path.isfile(env_path) else ""
    patches = carrier_patches(env_text, validate=False)
    shape = _shape(carrier_dir, base_tree_name, env_text)
    before = _snapshot(view, overlay_chain(lists))
    modified = apply_policy(view, lists, shape, carrier_sets_plugin_list(patches), runner, log)
    # Only an overlay file the policy rewrote is the platform's own artifact; a list trim alone leaves
    # NVIDIA's files as shipped, so a failure there is the integrator's to read, not a refusal.
    rewritten = {name for name, data in before.items() if _snapshot(view, [name]).get(name) != data}
    if modified:
        lists = view.overlay_lists()

    chain = overlay_chain(lists)
    reason = _skip_reason(flashed_tree, stock_tree)
    if reason is None:
        with tempfile.TemporaryDirectory() as scratch:
            result = replay(
                flashed_tree,
                [view.resolve(name) or name for name in chain],
                runner,
                scratch,
                stock_path=stock_tree,
            )
        reason = result.skipped
    if reason is not None:
        log(f"Boot overlay replay skipped: {reason}")
        replay_text = "skipped"
    elif result.no_integrator_properties:
        log("Boot overlay replay: the flashed tree equals the stock tree, so no integrator-set property can change")
        replay_text = "no integrator-set properties"
    else:
        for change in result.changes:
            log(
                f"  WARNING: integrator-set property {change.property} of {change.path} "
                f"changed by {change.overlay}: {_show(change.before)} -> {_show(change.after)}"
            )
        for failure in result.failures:
            detail = f": {failure.output.strip()}" if failure.output.strip() else ""
            log(f"  WARNING: boot overlay {failure.overlay} failed to apply in the replay (status {failure.status}){detail}")
        refused = [f.overlay for f in result.failures if f.overlay in rewritten]
        if refused:
            raise EngineError(
                f"boot overlay {', '.join(refused)} failed to apply in the replay after the camera policy "
                f"rewrote it; refusing before any board contact"
            )
        replay_text = (
            f"{len(result.applied)} applied, {len(result.changes)} property warning(s), "
            f"{len(result.failures)} failure(s)"
        )

    counts = ", ".join(
        f"{len(values or ())} {label}"
        for label, values in (
            ("bootcontrol", lists.bootcontrol),
            ("plugin-manager", lists.plugin_manager),
            ("extra", lists.extra),
        )
    )
    return (
        f"{SUMMARY_PREFIX} {counts}; camera policy {'modified' if modified else 'unchanged'}; "
        f"replay {replay_text}"
    )


def stage_for_provision(data_dir: str, man, work: Path, runner, log=print) -> str:
    """Resolve the carrier slot and the two trees from the staged work directory, then run the stage."""
    bsp = join_name(data_dir, man.tegraflash_bsp)
    stock_name = _selected_tree(str(bsp))
    flashed_name = _selected_tree(str(work))
    carrier_dir = join_name(data_dir, man.tegraflash_carrier_bsp) if man.tegraflash_carrier_bsp else None
    return stage(
        EffectiveView.work_dir(str(work)),
        join_name(bsp, stock_name) if stock_name else None,
        join_name(work, flashed_name) if flashed_name else None,
        runner,
        log,
        carrier_dir=str(carrier_dir) if carrier_dir and carrier_dir.is_dir() else None,
        base_tree_name=os.path.basename(stock_name),
    )
