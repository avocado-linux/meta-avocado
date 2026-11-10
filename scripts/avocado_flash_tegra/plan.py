"""Build the command line and environment for the provisioning script.

Standard library only.
"""

import shlex
from dataclasses import dataclass
from pathlib import Path

from avocado_flash_tegra import FlashError
from avocado_flash_tegra.inputs import PROFILE

AGENT_SOCK_VAR = "AVOCADO_AGENT_SOCK"
SYSTEM_PATH = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"


@dataclass(frozen=True)
class Invocation:
    argv: tuple[str, ...]
    env: dict[str, str]
    cwd: Path


def safe_path(caller_path: str) -> str:
    """The caller's PATH with only its absolute components.

    An empty or relative component means the current directory, which for the
    script is the deploy directory: root could then resolve jq, cpp or fdtget
    from a directory the caller does not control.
    """
    parts = [p for p in caller_path.split(":") if p.startswith("/")]
    return ":".join(parts) if parts else SYSTEM_PATH


def build_invocation(
    *,
    images_dir: Path,
    manifest: Path,
    script: Path,
    build_dir: Path,
    kernel_image: Path,
    helper_dir: Path,
    extra_path_dir: Path | None,
    is_root: bool,
    have_sudo: bool,
    caller_path: str,
    profile: str = PROFILE,
    cmdline_extra: str | None = None,
) -> Invocation:
    """Return the argv, explicit environment and cwd for the script.

    The environment is built from scratch so nothing of the caller's leaks
    in; the USB-reset agent socket variable is never added, and sudo is told
    to unset it as well in case a sudo policy would carry it over.
    """
    if not is_root and not have_sudo:
        raise FlashError(
            "the flash needs root: run as root or install sudo (the recovery-mode "
            "flash writes USB devices and root-owned files)"
        )
    path_parts = [str(helper_dir)]
    if extra_path_dir is not None:
        path_parts.append(str(extra_path_dir))
    path_parts.append(safe_path(caller_path))
    env = {
        "AVOCADO_STONE_MANIFEST": str(manifest),
        "AVOCADO_STONE_DATA_DIR": str(images_dir),
        "AVOCADO_STONE_BUILD_DIR": str(build_dir),
        "AVOCADO_PROVISION_PROFILE": profile,
        "AVOCADO_PROVISION_KERNEL_IMAGE": str(kernel_image),
        # The wrapper already confirmed the device with the operator.
        "AVOCADO_PROVISION_FORCE": "1",
        "PATH": ":".join(path_parts),
    }
    if cmdline_extra is not None:
        # The provisioning script appends its own root-partition pins to this, so it only adds arguments.
        env["AVOCADO_KERNEL_CMDLINE_EXTRA"] = cmdline_extra
    if is_root:
        argv = (str(script),)
    else:
        assignments = tuple(f"{k}={v}" for k, v in env.items())
        # env reads any operand containing "=" as another assignment, prints
        # the environment and exits 0, so the command operand must not have one.
        # The child runs in images_dir, so a script there is named relative to it.
        if script.parent == images_dir:
            command = f"./{script.name}"
        else:
            command = str(script)
        if "=" in command:
            raise FlashError(
                f"cannot run {script} through sudo env: the path contains '='; "
                "deploy the images under a path without one"
            )
        argv = ("sudo", "env", "-u", AGENT_SOCK_VAR, *assignments, command)
    return Invocation(argv=argv, env=env, cwd=images_dir)


def describe(invocation: Invocation) -> str:
    """Render the command, environment variables and working directory."""
    lines = ["command: " + " ".join(shlex.quote(a) for a in invocation.argv)]
    lines.append(f"working directory: {invocation.cwd}")
    lines.append("environment:")
    for key, value in invocation.env.items():
        lines.append(f"  {key}={value}")
    lines.append(f"  ({AGENT_SOCK_VAR} is removed)")
    return "\n".join(lines)
