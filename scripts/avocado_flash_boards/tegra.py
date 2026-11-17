"""Jetson boards, one per meta-avocado-nvidia stone manifest."""

from . import Board

VENDOR = "0955"  # NVIDIA

_ORIN_NANO_EVIDENCE = "lsusb on the bench Orin Nano showed 0955:7523 NVIDIA Corp. APX"

# Source of truth is each manifest's tegraflash.rcm_ids; this table is kept in step by
# scripts/tests/boards/test_manifest_sync.py until the wrapper is removed.
BOARDS = [
    Board("avocado-icam-540", "tegra"),
    Board("avocado-jetson-agx-orin", "tegra"),
    Board("avocado-jetson-agx-thor", "tegra"),
    Board("avocado-jetson-orin-nano", "tegra", "0955:7523", _ORIN_NANO_EVIDENCE),
    Board("avocado-jetson-orin-nx", "tegra"),
    Board("avocado-recomputer-j301x", "tegra"),
    Board("avocado-recomputer-j401x", "tegra"),
]
