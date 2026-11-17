"""Tegra flash engine: stdlib-only, Python 3.10+."""

from enum import Enum


class EngineError(Exception):
    """A fatal engine condition; the CLI prints ``ERROR: <text>`` and exits 1."""


class Media(Enum):
    NVME = "nvme"
    EMMC = "emmc"
    SD = "sd"
