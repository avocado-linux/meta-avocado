"""`avocado-flash` launcher entry (opt-in, AVOCADO_FLASH_LAUNCHER=1).

    main(argv, resolved) -> exit status

avocado-flash keeps deploy-tree and machine resolution (so "several build trees"
and "several machines" behave as before) and passes the result in as `resolved`.
This module parses the medium and its options, then hands one run to
run.run_stone, the single entry for a `stone provision` run. It starts no
write tool itself.

One function per medium route, so a later task wires a medium by replacing its
route and nothing else. nvme is first-argument only and parses its own small
option set (main_nvme); ums wraps the ums session (the board's USB mass storage
export) around the ums profile, with the console driver passed in as `host`.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

from .envmap import LauncherError, LaunchOpts, build_run_env, map_profile
from .inputs import _template_name, stone_dir_for
from .run import SIGINT_EXIT, RunContext, run_stone
from .ums import ums_session

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
    ap.add_argument("-p", "--port", default="/dev/ttyACM0")
    ap.add_argument("-k", "--keys", type=Path)
    ap.add_argument("--key-type")
    ap.add_argument("--spsdk-bin", type=Path)
    ap.add_argument("--commit", action="store_true")
    ap.add_argument("--interrupt", action="store_true")
    ap.add_argument("--ums-dev", default="mmc 1")
    ap.add_argument("--usb-controller", type=int, default=0)
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


def _context(resolved: Resolved, args) -> RunContext:
    return RunContext(
        deploy=resolved.deploy,
        machine=resolved.machine,
        images_dir=resolved.images_dir,
        manifest=_load_manifest(resolved),
        stale_ok=getattr(args, "stale_ok", False),
        workdir=args.workdir,
    )


def _provision(resolved: Resolved, opts: LaunchOpts, args) -> int:
    # The bmaptool refusal precedes every other piece of work, manifest reading included.
    build_run_env(opts, {}, map_profile(opts.medium, opts.boot_media))
    return run_stone(opts, _context(resolved, args))


def route_sd(resolved: Resolved, args) -> int:
    if not args.device:
        raise LauncherError("'sd' needs a device (see --help)")
    return _provision(resolved, _opts(args, "sd"), args)


def route_emmc(resolved: Resolved, args) -> int:
    return _provision(resolved, _opts(args, "emmc"), args)


def route_ums(resolved: Resolved, args, host=None) -> int:
    if args.device:
        raise LauncherError("the ums medium takes no device argument")
    if host is None:
        raise LauncherError("the ums medium needs the board console driver; none was supplied")
    opts = _opts(args, "ums")
    # Refusals that need no board come before the export is started.
    build_run_env(opts, {}, map_profile("ums"))
    ctx = _context(resolved, args)
    with ums_session(host, args.port, args.usb_controller, args.ums_dev) as disk:
        opts.exported_device = disk
        return run_stone(opts, ctx)


_ROUTES = {"sd": route_sd, "emmc": route_emmc}

_MID_WRITE = "the board may be mid-write and must be put in recovery mode again"


def _nvme_parser() -> argparse.ArgumentParser:
    class Parser(argparse.ArgumentParser):
        def error(self, message):
            raise LauncherError(f"nvme: {message}")

    ap = Parser(prog="avocado-flash nvme", description="Flash a Jetson in USB recovery mode.", allow_abbrev=False)
    ap.add_argument("-m", "--machine")
    ap.add_argument("-d", "--deploy", type=Path)
    ap.add_argument("-n", "--dry-run", action="store_true")
    ap.add_argument("-y", "--assume-yes", action="store_true")
    ap.add_argument("--workdir", type=Path)
    ap.add_argument("--rcm-id")
    ap.add_argument("--boot-media", choices=["nvme", "sd", "emmc"], default="nvme")
    ap.add_argument("--kernel-cmdline-extra")
    return ap


def route_nvme(resolved: Resolved, args) -> int:
    opts = LaunchOpts(
        medium="nvme",
        assume_yes=args.assume_yes,
        dry_run=args.dry_run,
        boot_media=args.boot_media,
        kernel_cmdline_extra=args.kernel_cmdline_extra,
        rcm_id=args.rcm_id,
    )
    kept: list[str] = []

    def out(message):
        print(message, file=sys.stderr)
        if "kept:" in message:
            kept.append(message.rsplit("kept:", 1)[1].strip())

    rc = run_stone(opts, _context(resolved, args), out=out)
    if rc == 0:
        if opts.dry_run:
            print("dry run: stone prepared the inputs only; the board was not contacted")
        else:
            print("Flash finished. Remove the FC_REC recovery jumper and power-cycle the board.")
            print("work directory: removed")
    elif kept:
        # 127 (stone never started) writes nothing, but the operator still needs the path.
        what = "interrupted" if rc == SIGINT_EXIT else f"the flash exited {rc}"
        print(f"{what}; {_MID_WRITE}.", file=sys.stderr)
        print(f"work directory: {kept[-1]}", file=sys.stderr)
    return rc


def main_nvme(argv: list[str], resolve_deploy_dir, resolve_machine) -> int:
    """`avocado-flash nvme [options]`; argv is everything after the word nvme.

    The options are parsed here, before deploy resolution, so a foreign option or a
    device argument is refused before any process starts. avocado-flash's own
    resolvers are passed in so "several build trees" and "several machines" behave
    as for every other medium.
    """
    try:
        args = _nvme_parser().parse_args(argv)
        deploy = resolve_deploy_dir(args.deploy)
        machine = resolve_machine(deploy, args.machine)
        resolved = Resolved(deploy=deploy, machine=machine, images_dir=Path(deploy) / "images" / machine)
        return route_nvme(resolved, args)
    except LauncherError as exc:
        print(f"avocado-flash: {exc}", file=sys.stderr)
        return 1


def main(argv: list[str], resolved: Resolved, host=None) -> int:
    try:
        args = _parser().parse_args(argv)
        if args.medium == "ums":
            return route_ums(resolved, args, host)
        return _ROUTES[args.medium](resolved, args)
    except LauncherError as exc:
        print(f"avocado-flash: {exc}", file=sys.stderr)
        return 1
