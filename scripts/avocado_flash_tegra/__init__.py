"""Shared definitions for the Jetson NVMe recovery-mode flash path.

Standard library only.
"""

from dataclasses import dataclass


class FlashError(Exception):
    """A refusal; the CLI prints it as ``avocado-flash: <text>`` and exits 1."""


@dataclass(frozen=True)
class Problem:
    """One thing wrong with the flash inputs.

    ``what`` says what is wrong; ``target`` is the bitbake target that
    produces the missing item, when one is known.
    """

    what: str
    target: str | None = None


@dataclass(frozen=True)
class InputInfo:
    """A flash input as described for the dry run and the free-space check."""

    name: str
    key: str
    size: int
    mtime: float


def format_problems(problems) -> str:
    """One line per problem, with the build target appended when known."""
    lines = []
    for p in problems:
        if p.target:
            lines.append(f"{p.what} (build target: {p.target})")
        else:
            lines.append(p.what)
    return "\n".join(lines)
