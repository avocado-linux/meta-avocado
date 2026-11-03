"""Expected USB recovery-mode id per machine.

Standard library only.
"""

import re

from . import FlashError

NVIDIA_VENDOR = "0955"

# devtool-debt: a one-entry table keyed by machine name.
# Ceiling: one machine.
# Upgrade trigger: a second Jetson machine is flashed through this tool.
RCM_IDS = {"avocado-jetson-orin-nano": "0955:7523"}

_ID_RE = re.compile(r"^([0-9a-f]{4}):([0-9a-f]{4})$")


def parse_rcm_id(text: str) -> str:
    """Validate a ``vvvv:pppp`` hex pair and return it lowercase."""
    m = _ID_RE.match(text.strip().lower())
    if not m:
        raise FlashError(
            f"invalid --rcm-id {text!r}: expected a vendor:product hex pair "
            f"such as {NVIDIA_VENDOR}:7523"
        )
    if m.group(1) != NVIDIA_VENDOR:
        raise FlashError(
            f"invalid --rcm-id {text!r}: vendor must be {NVIDIA_VENDOR} (NVIDIA)"
        )
    return m.group(0)


def expected_rcm_id(machine: str, override: str | None) -> str:
    """The recovery-mode USB id to pin for ``machine``; an override wins."""
    if override is not None:
        return parse_rcm_id(override)
    if machine in RCM_IDS:
        return RCM_IDS[machine]
    raise FlashError(
        f"no recovery-mode USB id is recorded for machine {machine}; "
        "pass it with --rcm-id vvvv:pppp"
    )
