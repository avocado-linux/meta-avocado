"""The one deliberate size deviation between the shipped Jetson profile and the kit's golden.

The kit's golden dry run (``golden/real-board-dry-run.txt``) is real recorded output and is
never edited. It records the data partition (``DATAPART_EXPAND``, partition 16) with
``size=119035295``. The shipped profile uses ``size=119035289``: the image's grow service
relocates the backup GPT with ``sgdisk -e``, which needs 6 sectors more room at the end of the
last partition.

Tests that compare the tool's table or plan body with the golden rewrite exactly that token in
the golden lines with ``kit_to_port_data_size`` and compare everything else unchanged, so any
other difference still fails.
"""

from __future__ import annotations

import re

KIT_DATA_SIZE = 119035295
PORT_DATA_SIZE = 119035289

_KIT_TOKEN = re.compile(rf"size={KIT_DATA_SIZE}(?!\d)")
_PORT_TOKEN = f"size={PORT_DATA_SIZE}"


def kit_to_port_data_size(golden_lines):
    """The golden lines with only ``size=<kit data size>`` rewritten to the shipped size.

    Asserts at least one line carried the token, so a golden that stops recording the kit's
    size cannot make the normalisation silently do nothing.
    """
    out = []
    hits = 0
    for ln in golden_lines:
        new, n = _KIT_TOKEN.subn(_PORT_TOKEN, ln)
        hits += n
        out.append(new)
    assert hits, f"golden no longer carries size={KIT_DATA_SIZE}"
    return out
