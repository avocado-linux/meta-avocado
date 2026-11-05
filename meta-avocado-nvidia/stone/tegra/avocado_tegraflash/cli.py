"""Engine command line. Stages are wired in task 6.1."""

import argparse
import sys
import time

from . import EngineError
from .runner import SubprocessRunner


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="avocado_tegraflash", add_help=False)
    parser.add_argument("--prepare-only", action="store_true")
    return parser


def _run(args, environ, runner, euid, sleep) -> int:
    raise EngineError("engine stages are not wired")


def main(argv=None, environ=None, runner=None, euid=None, sleep=time.sleep) -> int:
    argv = sys.argv[1:] if argv is None else list(argv)
    try:
        args = _parser().parse_args(argv)
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 2
    try:
        return _run(args, environ, runner or SubprocessRunner(), euid, sleep)
    except EngineError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
