"""`avocado-flash` launcher entry (opt-in, AVOCADO_FLASH_LAUNCHER=1).

    main(argv, resolved) -> exit status

avocado-flash keeps deploy-tree and machine resolution (so "several build trees"
and "several machines" behave as before) and passes the result in as `resolved`.
This module parses the medium and its options, then hands one run to
run.run_stone, the single entry for a `stone provision` run. It starts no
write tool itself.

One function per medium route, so a later task wires a medium by replacing its
route and nothing else. nvme and ums are not wired yet and say so.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

from .envmap import LauncherError, LaunchOpts, build_run_env, map_profile
from .inputs import _template_name, stone_dir_for
from .run import RunContext, run_stone

__all__ = ["Resolved", "main", "route_sd", "route_emmc", "route_ums", "route_nvme"]


@dataclass
class Resolved:
    deploy: Path
    machine: str
    images_dir: Path


def _parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="avocado-flash", add_help=False)
    ap.add_argument("-m", "--machine")
    ap.add_argument("-d", "--deploy", type=Path)
    ap.add_argument("-b", "--backend")
    ap.add_argument("-t", "--task")
    ap.add_argument("-n", "--dry-run", action="store_true")
    ap.add_argument("--stale-ok", action="store_true")
    ap.add_argument("-y", "--assume-yes", action="store_true")
    ap.add_argument("--workdir", type=Path)
    # Accepted so a shared command line parses; fuse-srk and ums read them in avocado-flash.
    ap.add_argument("-p", "--port")
    ap.add_argument("-k", "--keys", type=Path)
    ap.add_argument("--key-type")
    ap.add_argument("--spsdk-bin", type=Path)
    ap.add_argument("--commit", action="store_true")
    ap.add_argument("--interrupt", action="store_true")
    ap.add_argument("--ums-dev")
    ap.add_argument("--usb-controller", type=int)
    ap.add_argument("medium", choices=["sd", "emmc", "ums"])
    ap.add_argument("device", nargs="?")
    return ap


def _load_manifest(resolved: Resolved) -> dict:
    """The machine's manifest: the stone directory's when it has one, else the images directory's."""
    source = stone_dir_for(resolved.deploy, resolved.machine) or resolved.images_dir
    names = ("manifest.json", _template_name(resolved.machine), f"stone-{resolved.machine}.json")
    path = next((source / n for n in names if (source / n).is_file()), None)
    if path is None:
        raise LauncherError(f"no manifest for {resolved.machine} under {source}")
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        raise LauncherError(f"cannot read the manifest {path}: {exc}") from exc


def _opts(args, medium: str) -> LaunchOpts:
    return LaunchOpts(
        medium=medium,
        device=args.device,
        assume_yes=args.assume_yes,
        dry_run=args.dry_run,
        task=args.task,
        backend=args.backend,
    )


def _provision(resolved: Resolved, opts: LaunchOpts, args) -> int:
    # The bmaptool refusal precedes every other piece of work, manifest reading included.
    build_run_env(opts, {}, map_profile(opts.medium, opts.boot_media))
    ctx = RunContext(
        deploy=resolved.deploy,
        machine=resolved.machine,
        images_dir=resolved.images_dir,
        manifest=_load_manifest(resolved),
        stale_ok=args.stale_ok,
        workdir=args.workdir,
    )
    return run_stone(opts, ctx)


def route_sd(resolved: Resolved, args) -> int:
    if not args.device:
        raise LauncherError("'sd' needs a device (see --help)")
    return _provision(resolved, _opts(args, "sd"), args)


def route_emmc(resolved: Resolved, args) -> int:
    return _provision(resolved, _opts(args, "emmc"), args)


def route_ums(resolved: Resolved, args) -> int:
    raise LauncherError("the ums medium is not yet wired into the launcher (AVOCADO_FLASH_LAUNCHER=1)")


def route_nvme(resolved: Resolved, args=None) -> int:
    raise LauncherError("the nvme medium is not yet wired into the launcher (AVOCADO_FLASH_LAUNCHER=1)")


_ROUTES = {"sd": route_sd, "emmc": route_emmc, "ums": route_ums}


def main_nvme() -> int:
    try:
        return route_nvme(None)
    except LauncherError as exc:
        print(f"avocado-flash: {exc}", file=sys.stderr)
        return 1


def main(argv: list[str], resolved: Resolved) -> int:
    try:
        args = _parser().parse_args(argv)
        return _ROUTES[args.medium](resolved, args)
    except LauncherError as exc:
        print(f"avocado-flash: {exc}", file=sys.stderr)
        return 1
