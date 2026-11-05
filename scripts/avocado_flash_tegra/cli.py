"""Command line for ``avocado-flash nvme``.

Standard library only. The launcher passes in the host helpers it owns
(deploy and machine resolution, the retype confirmation) so this package
needs nothing from the launcher script.
"""

import argparse
import datetime
import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import avocado_flash_boards as boards

from . import FlashError, Problem, format_problems, inputs, plan, prereqs, rcm, workdir
from .flow import FlashContext, flash
from .runner import Interrupted, SubprocessRunner

PROG = "avocado-flash nvme"
# avocado_flash_tegra/cli.py -> scripts -> layer root
LAYER_ROOT = Path(__file__).resolve().parents[2]


@dataclass
class Host:
    resolve_deploy_dir: Callable
    resolve_machine: Callable
    confirm_destructive: Callable
    fatal: type


class _Usage(Exception):
    pass


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        raise _Usage(message)


def build_parser() -> argparse.ArgumentParser:
    p = _Parser(
        prog=PROG,
        description="Flash a Jetson Orin Nano's NVMe in USB recovery mode.",
    )
    p.add_argument("-m", "--machine", help="machine name (default: the one built)")
    p.add_argument("-d", "--deploy", type=Path, help="Yocto deploy directory")
    p.add_argument("-n", "--dry-run", action="store_true", help="validate and print the plan; write nothing")
    p.add_argument("-y", "--assume-yes", action="store_true", help="skip the typed confirmation")
    p.add_argument("--workdir", type=Path, help="work directory for the run (kept on failure)")
    p.add_argument("--rcm-id", help="recovery-mode USB id vvvv:pppp for another board")
    return p


def _fmt_mtime(ts: float) -> str:
    return datetime.datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")


def _run(argv, host, runner) -> int:
    args = build_parser().parse_args(argv)
    boards.all_boards()  # a bad registry entry refuses here, before any USB action

    deploy = host.resolve_deploy_dir(args.deploy)
    machine = host.resolve_machine(deploy, args.machine)
    images_dir = Path(deploy) / "images" / machine

    template = inputs.load_template(images_dir, machine)
    inputs.require_profile(template, machine)
    inputs.require_engine(template, machine)

    is_root = os.geteuid() == 0

    entries = inputs.image_entries(template)
    problems = list(inputs.check_images(images_dir, entries))
    if not is_root and shutil.which("sudo") is None:
        problems.append(Problem("the flash needs root: run as root or install sudo"))
    problems += prereqs.check_executables(images_dir, template)
    helper = prereqs.find_bootimg_helper(LAYER_ROOT)
    helper_issue = prereqs.helper_problem(helper)
    if helper_issue is not None:
        problems.append(helper_issue)
    # The root script resolves tools on plan.safe_path, so the pre-flight must too.
    search_path = plan.safe_path(os.environ.get("PATH", ""))
    mk_problems, extra_path_dir = prereqs.check_mkbootimg(
        images_dir,
        path=search_path,
        tools_dirname=prereqs.tools_dir_name(template) or prereqs.TOOLS_DIRNAME,
    )
    problems += mk_problems
    problems += prereqs.check_host_tools(path=search_path)
    fit_problems, fit_lines = prereqs.fit_report(images_dir, template, entries)
    problems += fit_problems
    if problems:
        raise FlashError(format_problems(problems))

    infos = inputs.describe_inputs(images_dir, entries)
    print("inputs: all present")
    for info in infos:
        print(f"  {info.name}  {info.size} bytes  {_fmt_mtime(info.mtime)}")
    for line in fit_lines:
        print(f"  {line}")

    expected_id = rcm.expected_rcm_id(machine, args.rcm_id)

    planned = workdir.planned_workdir(args.workdir, machine)
    workdir.require_space(planned, workdir.required_bytes(infos))

    pinned = rcm.pin(rcm.list_usb(runner), expected_id)
    print(f"pinned: {pinned.path} {pinned.vid}:{pinned.pid}")

    manifest = images_dir / inputs.template_name(machine)
    script = images_dir / prereqs.script_name(template)
    kernel_image = images_dir / "Image"

    if args.dry_run:
        invocation = plan.build_invocation(
            images_dir=images_dir,
            manifest=manifest,
            script=script,
            build_dir=planned,
            kernel_image=kernel_image,
            helper_dir=planned / "bin",
            extra_path_dir=extra_path_dir,
            is_root=is_root,
            have_sudo=shutil.which("sudo") is not None,
            caller_path=os.environ.get("PATH", ""),
        )
        print(f"machine: {machine}")
        print(f"deploy directory: {deploy}")
        print(f"manifest: {manifest}")
        print(f"boot image helper: {helper}")
        print(f"work directory: {planned}")
        print(plan.describe(invocation))
        return 0

    ctx = FlashContext(
        machine=machine,
        images_dir=images_dir,
        manifest=manifest,
        script=script,
        kernel_image=kernel_image,
        helper_source=helper,
        extra_path_dir=extra_path_dir,
        expected_id=expected_id,
        pinned=pinned,
        workdir=workdir.create_workdir(planned, default=args.workdir is None),
    )
    flash(ctx, host, runner, assume_yes=args.assume_yes)
    return 0


def main(argv, host, runner=None) -> int:
    """Run the nvme medium; argv is everything after the ``nvme`` word."""
    runner = runner or SubprocessRunner()
    try:
        return _run(list(argv), host, runner)
    except _Usage as exc:
        print(f"{PROG}: error: {exc}", file=sys.stderr)
        return 2
    except SystemExit as exc:  # --help
        return exc.code if isinstance(exc.code, int) else 0
    except Interrupted as exc:
        print(f"avocado-flash: {exc}", file=sys.stderr)
        return 130
    except KeyboardInterrupt:
        print("avocado-flash: interrupted", file=sys.stderr)
        return 130
    except EOFError:
        print(
            "avocado-flash: no terminal to read the confirmation from; "
            "pass --assume-yes to skip it",
            file=sys.stderr,
        )
        return 1
    except (FlashError, boards.BoardError) as exc:
        print(f"avocado-flash: {exc}", file=sys.stderr)
        return 1
    except host.fatal as exc:
        print(f"avocado-flash: {exc}", file=sys.stderr)
        return 1
