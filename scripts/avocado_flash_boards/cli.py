"""`avocado-flash boards`: list the machines the tool knows.

Pure registry read. It imports nothing that starts a process, so it is safe to
run with no board attached and no build tree.
"""

from __future__ import annotations

import sys

from . import BoardError, all_boards


def main(argv: list[str]) -> int:
    if argv:
        print("avocado-flash boards: takes no arguments")
        return 2
    try:
        boards = all_boards()
    except BoardError as exc:
        print(f"avocado-flash: {exc}", file=sys.stderr)
        return 1
    for board in boards:
        print(f"{board.machine} {board.family} {board.rcm_id or 'none recorded'}")
    return 0
