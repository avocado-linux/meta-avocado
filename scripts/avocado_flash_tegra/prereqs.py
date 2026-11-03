"""Checks for the executables, helper and host tools the flash needs.

Standard library only. Nothing here starts a process.
"""

import os
import shutil
from pathlib import Path

from . import Problem

PROFILE = "tegraflash-nvme"
HELPER_REL = Path(
    "meta-avocado-nvidia/recipes-avocado/sdk/avocado-sdk-target/avocado-tegra-bootimg"
)
HELPER_SHEBANG = "#!/bin/sh"
TOOLS_DIRNAME = "tegraflash-tools"
HOST_TOOLS = ("jq", "fdtget", "fdtput", "cpp", "lsusb")


def _is_executable_file(path: Path) -> bool:
    return path.is_file() and os.access(path, os.X_OK)


def check_executables(images_dir, template) -> list[Problem]:
    images_dir = Path(images_dir)
    problems: list[Problem] = []

    script_name = template["provision"]["profiles"][PROFILE]["script"]
    script = images_dir / script_name
    if not _is_executable_file(script):
        problems.append(
            Problem(
                f"the provisioning script {script_name} is missing or not "
                f"executable in {images_dir}",
                "avocado-stone",
            )
        )

    tools_name = template["storage_devices"]["rootdisk"]["images"]["tegraflash_tools"]
    initrd_flash = images_dir / tools_name / "initrd-flash"
    if not _is_executable_file(initrd_flash):
        problems.append(
            Problem(
                f"{initrd_flash} is missing or not executable",
                "tegraflash-tools-deploy",
            )
        )

    kernel = images_dir / "Image"
    if not kernel.is_file() or kernel.stat().st_size == 0:
        problems.append(
            Problem(
                f"the kernel image {kernel} is missing or empty, so the boot "
                "image could not pin the rootfs"
            )
        )
    return problems


def find_bootimg_helper(layer_root) -> Path | None:
    """The helper is committed mode 100644, so only the shebang is checked."""
    helper = Path(layer_root) / HELPER_REL
    if not helper.is_file():
        return None
    try:
        with helper.open("r", encoding="utf-8", errors="replace") as fh:
            first = fh.readline().rstrip("\r\n")
    except OSError:
        return None
    return helper if first == HELPER_SHEBANG else None


def helper_problem(helper) -> Problem | None:
    if helper is not None:
        return None
    return Problem(
        "avocado-tegra-bootimg was not found, so the flash would boot an image "
        "that does not name its rootfs"
    )


def check_mkbootimg(images_dir, path=None) -> tuple[list[Problem], Path | None]:
    """Return problems and the directory to prepend to PATH, if one is needed."""
    if shutil.which("mkbootimg", path=path):
        return [], None
    tools_dir = Path(images_dir) / TOOLS_DIRNAME
    if _is_executable_file(tools_dir / "mkbootimg"):
        return [], tools_dir
    return (
        [
            Problem(
                "mkbootimg is neither executable under "
                f"{tools_dir} nor on the search path; the boot image helper "
                "refuses a non-executable mkbootimg"
            )
        ],
        None,
    )


def check_host_tools(path=None) -> list[Problem]:
    return [
        Problem(f"host tool {tool} is not on the search path")
        for tool in HOST_TOOLS
        if shutil.which(tool, path=path) is None
    ]
