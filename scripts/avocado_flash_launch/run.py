"""Orchestrate one `stone provision` run (everything injectable; no hidden state).

    run_stone(opts, ctx, ...) -> exit code

Order of operations, so a refusal leaves no scratch directory behind:
bmaptool refusal and profile checks -> tool lookup -> root/sudo availability
for a real tegraflash run -> create the scratch -> assemble inputs -> run stone
-> clean up.

Privilege split: stone runs as the invoking user for every non-tegraflash
profile and for a tegraflash dry run (prepare-only, no board contact). A real
tegraflash run is started whole under sudo with a fixed explicit environment,
a PATH reduced to absolute components, and AVOCADO_AGENT_SOCK removed.
"""

from __future__ import annotations

import os
import secrets
import shutil
import signal
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from .envmap import LauncherError, LaunchOpts, OWNED_VARS, build_run_env, map_profile
from .inputs import (
    assemble_inputs,
    check_profile,
    jetson_kernel_image,
    stale_check,
    stone_dir_for,
    var_size_bytes,
)
from .scratch import capture, create_scratch, plan_scratch, remove_scratch
from .tools import check_tegra_tools, find_stone, make_sysroot_lookup

__all__ = ["RunContext", "run_stone", "safe_path", "SIGINT_EXIT"]

AGENT_SOCK_VAR = "AVOCADO_AGENT_SOCK"
SYSTEM_PATH = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
SIGINT_EXIT = 130

# Inherited variables removed from the child env (non-root runs inherit everything
# outside OWNED_VARS). avocado-safe-disk.sh reads each with no test gate, so an
# exported value would point the system-disk, mounted and swap checks at fake data:
#   SYSBLOCK           sysfs block dir the root-disk and partition checks walk
#   MOUNTS, SWAPS      mount and swap tables the "in use" checks read
#   DEVDIR             where device nodes are resolved
#   EUID               the uid the library claims to act as
#   CONTAINER_MARKERS  files whose presence flips the container detection
SEAM_VARS = (
    "AVOCADO_PROVISION_SYSBLOCK",
    "AVOCADO_SAFE_DISK_MOUNTS",
    "AVOCADO_SAFE_DISK_SWAPS",
    "AVOCADO_SAFE_DISK_DEVDIR",
    "AVOCADO_SAFE_DISK_EUID",
    "AVOCADO_SAFE_DISK_CONTAINER_MARKERS",
)


@dataclass
class RunContext:
    deploy: Path
    machine: str
    images_dir: Path
    manifest: dict
    stale_ok: bool = False
    workdir: Path | None = None


def safe_path(caller_path: str) -> str:
    """The caller's PATH reduced to absolute components.

    An empty or relative component means the current directory, from which root
    could otherwise resolve a tool the caller controls.
    """
    parts = [p for p in caller_path.split(":") if p.startswith("/")]
    return ":".join(parts) if parts else SYSTEM_PATH


def _err(message):
    print(message, file=sys.stderr)


def _python3_version(which, capture_fn):
    exe = which("python3")
    if not exe:
        return None
    rc, out = capture_fn([exe, "-c", "import sys; print(sys.version_info[0], sys.version_info[1])"])
    if rc != 0:
        return None
    try:
        major, minor = out.split()[:2]
        return int(major), int(minor)
    except ValueError:
        return None


def _fixed_env(env: dict[str, str], additions: dict[str, str]) -> dict[str, str]:
    """The explicit environment for a root run: launcher-owned variables, PATH, library path.

    Nothing else of the caller's leaks in, and the USB-reset agent socket is never added.
    """
    fixed = {k: v for k, v in env.items() if k in OWNED_VARS}
    fixed["PATH"] = safe_path(additions.get("PATH", env.get("PATH", "")))
    ld = additions.get("LD_LIBRARY_PATH", env.get("LD_LIBRARY_PATH"))
    if ld:
        fixed["LD_LIBRARY_PATH"] = ld
    fixed.pop(AGENT_SOCK_VAR, None)
    return fixed


def _wait_child(popen, argv, env, cwd):
    """Start argv and wait for it; return (returncode, interrupted).

    SIGINT is absorbed once the child runs (the terminal's signal already
    reached its process group, and this process never signals it): killing
    stone mid-write could leave the board half-flashed.
    """
    interrupted = False

    def absorb(signum, frame):
        nonlocal interrupted
        interrupted = True

    proc = popen(list(argv), env=env, cwd=str(cwd))
    installed = True
    try:
        previous = signal.signal(signal.SIGINT, absorb)
    except ValueError:  # not the main thread: the loop below still copes
        installed = False
    try:
        while True:
            try:
                rc = proc.wait()
                break
            except KeyboardInterrupt:
                interrupted = True
    finally:
        if installed:
            signal.signal(signal.SIGINT, previous or signal.SIG_DFL)
    return rc, interrupted


def run_stone(
    opts: LaunchOpts,
    ctx: RunContext,
    *,
    uid: int | None = None,
    which=shutil.which,
    environ: dict[str, str] | None = None,
    popen=subprocess.Popen,
    capture_fn=capture,
    sysroot_lookup=None,
    python_version=None,
    token_hex=secrets.token_hex,
    out=_err,
) -> int:
    uid = os.geteuid() if uid is None else uid
    environ = dict(os.environ) if environ is None else dict(environ)

    profile = map_profile(opts.medium, opts.boot_media)
    build_run_env(opts, environ, profile)  # bmaptool and ums refusals come first
    check_profile(ctx.manifest, ctx.machine, profile, opts.dry_run)
    jetson = profile.startswith("tegraflash-")
    kernel = jetson_kernel_image(ctx.images_dir) if jetson else None
    var_bytes = var_size_bytes(ctx.manifest, ctx.images_dir)
    env, warnings = build_run_env(opts, environ, profile, kernel)
    for var in SEAM_VARS:
        if var in env:
            warnings.append(
                f"warning: ignoring inherited {var}={env.pop(var)!r}; "
                "it is a test override of the safe-disk checks and is never passed to stone"
            )

    lookup = sysroot_lookup or make_sysroot_lookup(ctx.deploy)
    stone, additions = find_stone(
        lookup, which, base_path=environ.get("PATH", ""), base_ld=environ.get("LD_LIBRARY_PATH", "")
    )
    stone = Path(os.path.abspath(stone))
    if jetson:
        version = python_version if python_version is not None else _python3_version(which, capture_fn)
        check_tegra_tools(which, version)
    stone_dir = stone_dir_for(ctx.deploy, ctx.machine)
    stale_check(stone_dir, ctx.images_dir, ctx.stale_ok)

    real_tegra = jetson and not opts.dry_run
    sudo = None
    if real_tegra and uid != 0:
        sudo = which("sudo")
        if not sudo:
            raise LauncherError(
                "the flash needs root: run as root or install sudo (the recovery-mode "
                "flash writes USB devices and root-owned files)"
            )
    if real_tegra and "=" in str(stone):
        # env reads an operand containing '=' as another assignment and exits 0.
        raise LauncherError(f"cannot run {stone} through sudo env: the path contains '='")

    scratch_path = plan_scratch(ctx.workdir, ctx.deploy, uid, token_hex)
    scratch = create_scratch(scratch_path, uid)
    for message in warnings:
        out(message)

    try:
        assemble_inputs(ctx.machine, stone_dir, ctx.images_dir, scratch.path)
    except BaseException:
        remove_scratch(scratch)  # nothing has run yet, so nothing is worth keeping
        raise

    stone_argv = [str(stone), "provision", "-i", str(scratch.path), "--partition-size", f"var={var_bytes}"]
    if real_tegra:
        run_env = _fixed_env(env, additions)
        if sudo:
            assignments = [f"{k}={v}" for k, v in run_env.items()]
            argv = [sudo, "env", "-u", AGENT_SOCK_VAR, *assignments, *stone_argv]
        else:
            argv = stone_argv
    else:
        run_env = {**env, **additions}
        argv = stone_argv

    try:
        rc, interrupted = _wait_child(popen, argv, run_env, scratch.path)
    except OSError as exc:
        out(f"avocado-flash: cannot start {argv[0]}: {exc}")
        out(f"avocado-flash: scratch directory kept: {scratch.path}")
        return 127

    if interrupted:
        out(f"avocado-flash: interrupted; scratch directory kept: {scratch.path}")
        return SIGINT_EXIT
    if rc != 0:
        out(f"avocado-flash: stone exited {rc}; scratch directory kept: {scratch.path}")
        return rc
    left = remove_scratch(scratch, sudo=sudo, capture_fn=capture_fn)
    if left is not None:
        out(f"avocado-flash: scratch directory left on disk: {left}")
    return 0
