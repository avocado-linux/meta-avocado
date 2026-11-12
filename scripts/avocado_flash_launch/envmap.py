"""Launcher option to `stone provision` environment mapping (pure, no I/O).

Public API (stable for the launcher modules):

    LauncherError            raised with a user-facing message; the launcher exits non-zero
    LaunchOpts               parsed options (medium, device, assume_yes, dry_run, task,
                             backend, boot_media, kernel_cmdline_extra, rcm_id)
    OWNED_VARS               the variables the launcher sets from its own options alone
    map_profile(medium, boot_media) -> profile name
    build_run_env(opts, inherited, profile, kernel_image=None) -> (env, warnings)

build_run_env returns a new environment: `inherited` with every owned variable
removed and then set only from the options. A discarded inherited value that
differs from what the launcher sets (or the launcher sets none) yields one
warning naming the variable and the discarded value. FORCE is always set, to
"1" with -y and "0" otherwise, so an exported FORCE=1 never skips the retype.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["LauncherError", "LaunchOpts", "OWNED_VARS", "map_profile", "build_run_env"]

OWNED_VARS = (
    "AVOCADO_PROVISION_FORCE",
    "AVOCADO_PROVISION_DRY_RUN",
    "AVOCADO_PROVISION_FWUP_TASK",
    "AVOCADO_PROVISION_DEVICE",
    "AVOCADO_KERNEL_CMDLINE_EXTRA",
    "AVOCADO_PROVISION_KERNEL_IMAGE",
    "AVOCADO_PROVISION_RCM_ID",
    "AVOCADO_PROVISION_PROFILE",
)

_SIMPLE_PROFILES = {"sd": "sd", "emmc": "uuu-emmc", "ums": "ums"}
_JETSON_BOOT_MEDIA = ("nvme", "sd", "emmc")


class LauncherError(Exception):
    pass


@dataclass
class LaunchOpts:
    medium: str
    device: str | None = None
    assume_yes: bool = False
    dry_run: bool = False
    task: str | None = None
    backend: str | None = None
    boot_media: str = "nvme"
    kernel_cmdline_extra: str | None = None
    rcm_id: str | None = None


def map_profile(medium: str, boot_media: str = "nvme") -> str:
    if medium in _SIMPLE_PROFILES:
        return _SIMPLE_PROFILES[medium]
    if medium == "nvme":
        if boot_media not in _JETSON_BOOT_MEDIA:
            raise LauncherError(f"unknown --boot-media {boot_media!r}")
        return f"tegraflash-{boot_media}"
    raise LauncherError(f"medium {medium!r} has no provisioning profile")


def build_run_env(
    opts: LaunchOpts,
    inherited: dict[str, str],
    profile: str,
    kernel_image: str | None = None,
) -> tuple[dict[str, str], list[str]]:
    # bmaptool is refused before any other check.
    if opts.backend == "bmaptool":
        raise LauncherError("bmaptool is no longer offered; use the default backend")
    if opts.medium == "ums" and opts.device:
        raise LauncherError("the ums medium takes no device argument")

    jetson = profile.startswith("tegraflash-")
    nvme = opts.medium == "nvme"
    mapped: dict[str, str] = {
        "AVOCADO_PROVISION_FORCE": "1" if opts.assume_yes else "0",
        "AVOCADO_PROVISION_PROFILE": profile,
    }
    if opts.dry_run:
        mapped["AVOCADO_PROVISION_DRY_RUN"] = "1"
    if opts.medium == "sd" and opts.task:
        mapped["AVOCADO_PROVISION_FWUP_TASK"] = opts.task
    if opts.device:
        mapped["AVOCADO_PROVISION_DEVICE"] = opts.device
    if nvme and opts.kernel_cmdline_extra:
        mapped["AVOCADO_KERNEL_CMDLINE_EXTRA"] = opts.kernel_cmdline_extra
    if nvme and opts.rcm_id:
        mapped["AVOCADO_PROVISION_RCM_ID"] = opts.rcm_id
    if jetson and kernel_image:
        mapped["AVOCADO_PROVISION_KERNEL_IMAGE"] = kernel_image

    warnings: list[str] = []
    env = {k: v for k, v in inherited.items() if k not in OWNED_VARS}
    for var in OWNED_VARS:
        if var in inherited and inherited[var] != mapped.get(var):
            warnings.append(
                f"warning: ignoring inherited {var}={inherited[var]!r}; "
                "the launcher sets it from its own options alone"
            )
    env.update(mapped)
    return env, warnings
