"""The engine's view of the environment the oracle reads (stone provision hook)."""

import platform
from dataclasses import dataclass
from typing import Mapping

from . import EngineError
from .toolchain import DEFAULT_PYTHONWARNINGS

_REQUIRED = (
    "AVOCADO_STONE_MANIFEST",
    "AVOCADO_STONE_BUILD_DIR",
    "AVOCADO_STONE_DATA_DIR",
)

_CMDLINE_VARS = ("AVOCADO_KERNEL_CMDLINE", "AVOCADO_KERNEL_CMDLINE_EXTRA")


@dataclass(frozen=True)
class Config:
    manifest: str
    build_dir: str
    data_dir: str
    sdk_prefix: str
    sdk_arch: str
    cc: str
    profile: str
    sd_device: str
    kernel_image: str
    kernel_version: str
    kernel_cmdline: str
    kernel_cmdline_extra: str
    boardctl_target: str
    boardctl_serial: str
    pythonwarnings: str
    home: str
    erase_nvme: bool
    erase_emmc: bool
    erase_only: bool
    # None: AVOCADO_PROVISION_FORCE unset; True: 1; False: 0.
    force: bool | None = None
    # AVOCADO_PROVISION_NVME_PCI; empty when unset. Validated where it is used.
    nvme_pci: str = ""


def from_environ(environ: Mapping[str, str]) -> Config:
    """Build a Config; the default SDK arch is the host's `platform.machine()`.

    Defaults follow the shell's `${VAR:-default}`, so an empty optional
    variable counts as unset. Required variables are checked before anything
    else so a refusal never follows partial work.
    """
    for name in _REQUIRED:
        if not environ.get(name):
            raise EngineError(f"{name} is not set")

    # Both values reach the root-run boot image helper, which replaces or
    # appends the kernel command line, so a control character or newline
    # would be read as more than arguments.
    for name in _CMDLINE_VARS:
        if any(ord(c) < 0x20 or ord(c) == 0x7F for c in environ.get(name, "")):
            raise EngineError(f"{name} contains a control character or a newline")

    force_raw = environ.get("AVOCADO_PROVISION_FORCE", "")
    if force_raw not in ("", "0", "1"):
        raise EngineError(f"AVOCADO_PROVISION_FORCE must be 1, 0 or unset, not {force_raw!r}")
    force = None if force_raw == "" else force_raw == "1"

    def opt(name: str, default: str = "") -> str:
        return environ.get(name) or default

    return Config(
        manifest=environ["AVOCADO_STONE_MANIFEST"],
        build_dir=environ["AVOCADO_STONE_BUILD_DIR"],
        data_dir=environ["AVOCADO_STONE_DATA_DIR"],
        sdk_prefix=opt("AVOCADO_SDK_PREFIX"),
        sdk_arch=opt("AVOCADO_SDK_ARCH", platform.machine()),
        cc=opt("CC"),
        profile=opt("AVOCADO_PROVISION_PROFILE", "tegraflash"),
        sd_device=opt("AVOCADO_PROVISION_SD_DEVICE"),
        kernel_image=opt("AVOCADO_PROVISION_KERNEL_IMAGE"),
        kernel_version=opt("AVOCADO_PROVISION_KERNEL_VERSION", "?"),
        kernel_cmdline=opt("AVOCADO_KERNEL_CMDLINE"),
        kernel_cmdline_extra=opt("AVOCADO_KERNEL_CMDLINE_EXTRA"),
        boardctl_target=opt("BOARDCTL_TARGET"),
        boardctl_serial=opt("BOARDCTL_SERIAL"),
        pythonwarnings=opt("PYTHONWARNINGS", DEFAULT_PYTHONWARNINGS),
        home=opt("HOME", "/root"),
        erase_nvme=environ.get("ERASE_NVME") == "1",
        erase_emmc=environ.get("ERASE_EMMC") == "1",
        erase_only=environ.get("ERASE_ONLY") == "1",
        force=force,
        nvme_pci=opt("AVOCADO_PROVISION_NVME_PCI"),
    )
