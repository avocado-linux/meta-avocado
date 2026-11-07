"""Registry of the boards avocado-flash knows how to write.

Standard library only. The registry is validated the first time it is read,
so a bad entry stops every command that reads it (`nvme` and `boards`) with
a refusal naming the entry rather than one flash. Each family module exports
its ``VENDOR`` (the USB vendor of its recovery-mode id) and its ``BOARDS``.
"""

import functools
import re
from dataclasses import dataclass


class BoardError(Exception):
    """A registry or lookup refusal."""


_ID_RE = re.compile(r"^([0-9a-f]{4}):([0-9a-f]{4})$")


@dataclass(frozen=True)
class Board:
    machine: str
    family: str
    rcm_id: str | None = None
    rcm_evidence: str | None = None


def _family_name(module) -> str:
    return module.__name__.rpartition(".")[2]


def family_vendors(modules) -> dict[str, str]:
    """Map each family module's name to its VENDOR; a module without one is refused."""
    vendors: dict[str, str] = {}
    for module in modules:
        name = _family_name(module)
        vendor = getattr(module, "VENDOR", None)
        if not isinstance(vendor, str) or not re.fullmatch(r"[0-9a-f]{4}", vendor):
            raise BoardError(
                f"family {name}: VENDOR must be a lowercase 4-digit hex USB vendor id, "
                f"got {vendor!r}"
            )
        vendors[name] = vendor
    return vendors


def load(boards, vendors: dict[str, str]) -> dict[str, Board]:
    """Check ``boards`` against the ``vendors`` of the known families and return them keyed by machine."""
    registry: dict[str, Board] = {}
    for b in boards:
        if b.family not in vendors:
            raise BoardError(
                f"board {b.machine}: unknown family {b.family!r}; "
                f"known families are {', '.join(sorted(vendors))}"
            )
        if b.machine in registry:
            raise BoardError(f"duplicate board entry for machine {b.machine}")
        if b.rcm_id is not None:
            m = _ID_RE.fullmatch(b.rcm_id)
            if not m:
                raise BoardError(
                    f"board {b.machine}: recovery id {b.rcm_id!r} is not a "
                    "lowercase vendor:product hex pair"
                )
            if m.group(1) != vendors[b.family]:
                raise BoardError(
                    f"board {b.machine}: recovery id {b.rcm_id!r} must have "
                    f"vendor {vendors[b.family]} for family {b.family}"
                )
            if not (b.rcm_evidence or "").strip():
                raise BoardError(
                    f"board {b.machine}: recovery id {b.rcm_id} has no evidence"
                )
        registry[b.machine] = b
    return registry


from . import tegra  # noqa: E402  (needs Board defined above)

FAMILIES = (tegra,)

NVIDIA_VENDOR = tegra.VENDOR


def parse_recovery_id(text: str) -> str:
    """Validate a ``--rcm-id`` override and return it lowercase."""
    m = _ID_RE.match(text.strip().lower())
    if not m:
        raise BoardError(
            f"invalid --rcm-id {text!r}: expected a vendor:product hex pair "
            f"such as {NVIDIA_VENDOR}:7523"
        )
    if m.group(1) != NVIDIA_VENDOR:
        raise BoardError(
            f"invalid --rcm-id {text!r}: vendor must be {NVIDIA_VENDOR} (NVIDIA)"
        )
    return m.group(0)


@functools.cache
def _registry() -> dict[str, Board]:
    return load(
        [b for family in FAMILIES for b in family.BOARDS],
        family_vendors(FAMILIES),
    )


def all_boards() -> list[Board]:
    return list(_registry().values())


def lookup(machine: str) -> Board:
    try:
        return _registry()[machine]
    except KeyError:
        raise BoardError(
            f"unknown machine {machine}; run `avocado-flash boards` to list "
            "the machines this tool knows"
        ) from None
