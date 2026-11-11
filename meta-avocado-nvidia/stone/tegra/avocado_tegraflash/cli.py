"""Engine command line: the oracle's stages, wired in the oracle's order.

Oracle: tests/parity/legacy/stone-provision-tegraflash.sh. Line ranges in the
comments below say where each stage comes from.
"""

import argparse
import contextlib
import fcntl
import os
import sys
import tempfile
import time
from pathlib import Path

from . import (
    EngineError,
    bootimg,
    bootpriority,
    carrier,
    confirm,
    cpp,
    flash,
    partuuid,
    recovery,
    settings,
    staging,
    toolchain,
)
from .env import from_environ
from .fit import require_fit
from .manifest import read_manifest, require_image_keys
from .profile import media_for_profile
from .runner import SubprocessRunner

# Names no variable and no module on purpose: the refusal must not read the
# environment, and a hand-built list of variables forwards only some of the ones
# the engine reads, so the rerun would flash a different configuration. `sudo -E`
# keeps all of them and the caller's own command line keeps the entry point.
_ROOT_REQUIRED = (
    "root is required: the flash talks to the board over USB and the flash "
    "tool needs root.\n"
    "Run the same command again with sudo, keeping the environment and PATH:\n"
    '  sudo -E env PATH="$PATH" <the command you just ran>'
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="avocado_tegraflash", add_help=False)
    parser.add_argument("--prepare-only", action="store_true")
    return parser


@contextlib.contextmanager
def _build_dir_lock(build_dir: str):
    """Deviation build-dir-locked: one provisioning run per build directory.

    The lock file sits beside the work directory because the staging reset
    deletes that tree. The OS drops the lock when the process ends, crash included.
    """
    try:
        os.makedirs(build_dir, exist_ok=True)
        fh = open(Path(build_dir) / "tegraflash.lock", "a")
    except OSError as exc:
        raise EngineError(f"cannot create the lock file in {build_dir}: {exc}") from exc
    with fh:
        try:
            fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise EngineError(
                f"another provisioning run is using the build directory {build_dir}"
            ) from None
        yield


def _run(args, environ, runner, euid, sleep) -> int:
    # Deviation root-check-first: before the environment is read or anything is created.
    if not args.prepare_only and (os.geteuid() if euid is None else euid) != 0:
        raise EngineError(_ROOT_REQUIRED)

    base = dict(os.environ if environ is None else environ)
    cfg = from_environ(base)
    # Deviation unknown-profile-refused: the oracle (514-527) falls back to nvme.
    media = media_for_profile(cfg.profile)
    path_env = base.get("PATH", "")
    work = Path(cfg.build_dir) / "tegraflash"

    # Oracle 23-44: adb warm-up, best effort. The oracle (line 36) searches only
    # <data dir>/tegraflash-tools, by that literal name: the manifest is not read yet.
    toolchain.warm_adb(
        runner,
        data_dir=Path(cfg.data_dir) / "tegraflash-tools",
        home=cfg.home,
        env={**base, "PYTHONWARNINGS": cfg.pythonwarnings},
    )

    print("=== Tegraflash Provisioning Script ===")
    # A provision log must show which implementation ran without inferring it from missing output.
    print(f"Engine: {__package__} from {Path(__file__).resolve().parent}")
    print(f"Manifest: {cfg.manifest}")
    print(f"Data dir: {cfg.data_dir}")
    print(f"Build dir: {cfg.build_dir}")
    print(f"SDK prefix: {cfg.sdk_prefix or '<not set>'}")

    # Oracle 58-103: manifest read.
    man = read_manifest(cfg.manifest)
    require_image_keys(man)

    # Oracle 105-247 and 249-342: reset, BSP, tools, carrier, images, overlay check.
    with _build_dir_lock(cfg.build_dir):
        # Before the reset, so an unusable image leaves the previous staging intact.
        staging.require_images(Path(cfg.data_dir), man)
        staging.reset_work_dir(work)
        print(f"Building tegraflash working directory: {work}")
        staging.copy_bsp(cfg.data_dir, man.tegraflash_bsp, work)
        staging.copy_tools(cfg.data_dir, man.tegraflash_tools, cfg.sdk_prefix, work)
        if man.tegraflash_carrier_bsp:
            carrier.apply_carrier(cfg.data_dir, man.tegraflash_carrier_bsp, str(work))
        staging.copy_images(cfg.data_dir, man, work)
        staging.verify_overlays(man, work)

        # Oracle 344-346: the wrapper directory is removed on every way out.
        with tempfile.TemporaryDirectory() as wrapper_dir:
            # Oracle 348-377, resolved against the PATH the flash would otherwise
            # see. Deviation absolute-cpp-wrapper.
            target = cpp.resolve_cpp(path=path_env, sdk_arch=cfg.sdk_arch, cc=cfg.cc)
            cpp.write_wrapper(wrapper_dir, target)
            return _provision(args, cfg, man, media, work, wrapper_dir, base, runner, sleep)


def _provision(args, cfg, man, media, work, wrapper_dir, base, runner, sleep) -> int:
    # Oracle 382-431: the pins and the command line extra exist only on the kernel path.
    pins = partuuid.new_pins() if cfg.kernel_image else None
    extra = {}
    if pins:
        extra["AVOCADO_KERNEL_CMDLINE_EXTRA"] = partuuid.append_cmdline(cfg.kernel_cmdline_extra, pins)
    # Oracle 379-380 and 21: PATH and PYTHONWARNINGS as the flash tool sees them.
    flash_env = toolchain.flash_environment(
        base,
        wrapper_dir=wrapper_dir,
        work_dir=work,
        pythonwarnings=cfg.pythonwarnings,
        extra=extra,
    )

    # Oracle 401-454: repack with the pinned kernel, or keep the prebuilt boot image.
    if cfg.kernel_image:
        bootimg.repack(
            runner,
            work_dir=work,
            kernel_image=cfg.kernel_image,
            initramfs_name=man.initramfs,
            env=flash_env,
            version=cfg.kernel_version,
        )
    else:
        bootimg.refuse_cmdline_without_kernel(cfg.kernel_cmdline, cfg.kernel_cmdline_extra)
        bootimg.warn_prebuilt_boot_image()

    # Oracle 456-510: the recovery wait. Deviation one-board-only; deviation
    # prepare-only makes no board contact at all.
    board = None
    if not args.prepare_only:
        board = recovery.wait_for_single_board(
            runner,
            flash_env,
            boardctl_target=cfg.boardctl_target,
            boardctl_serial=cfg.boardctl_serial,
            sleep=sleep,
            expected_ids=man.rcm_ids,
        )

    # Oracle 512-597: boot device settings; an SD device from the environment wins.
    print(f"Boot media target: {media.value} (profile: {cfg.profile})")
    device = settings.apply_boot_device(work, media, sd_device=cfg.sd_device or man.sd_device)
    # The staged env file is final here. The flash sources it with bash, so what it
    # will use is read back instead of assumed; before the fit check, which reads it too.
    device = settings.verify_staged_env(work, man, device)

    # Hardware-free, so it also runs under --prepare-only; refuses before any erase.
    # After the eMMC layout swap above, and after the wait: the parity harness pins
    # both, because the oracle fails a missing layout only after the wait.
    require_fit(work, man)

    # Oracle 599-627.
    bootpriority.set_first(runner, work, media, env=flash_env)

    # Oracle 629-669: after the media case, which may swap the layout file in.
    if pins:
        partuuid.apply_layout(work, pins)
    else:
        partuuid.blank_layout(work)

    # Oracle 671-679.
    flags = flash.erase_flags(
        media,
        erase_nvme=cfg.erase_nvme,
        erase_emmc=cfg.erase_emmc,
        erase_only=cfg.erase_only,
    )
    print(f"Flash arguments: {' '.join(flags)}")

    # Deviation prepare-only: stop with the work directory and the command.
    if args.prepare_only:
        print(f"Work directory: {work}")
        print(f"Command: {' '.join(['./initrd-flash', *flags])}")
        return 0

    # Deviation device-confirmation: after the prepare-only return, so it never
    # prompts without a flash; before the recheck, so the operator confirms the
    # board the flash will see.
    confirm.confirm_device(
        board, media, flags=flags, device=device, force=cfg.force, isatty=confirm.stdin_is_tty, read=input
    )

    # Deviation one-board-only: the flash starts right after this check, on the
    # board the wait saw and no other.
    recovery.recheck_single_board(runner, flash_env, board, expected_ids=man.rcm_ids)

    # Oracle 680-694.
    print("Running initrd-flash script from build directory")
    return flash.run_flash(runner, work, flags, flash_env)


def main(argv=None, environ=None, runner=None, euid=None, sleep=time.sleep) -> int:
    # Piped stdout is block-buffered, so without this the engine's lines surface after
    # the output of the flash tools it runs, and the provision log reads out of order.
    reconfigure = getattr(sys.stdout, "reconfigure", None)
    if reconfigure is not None:
        reconfigure(line_buffering=True)
    argv = sys.argv[1:] if argv is None else list(argv)
    try:
        args = _parser().parse_args(argv)
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 2
    try:
        return _run(args, environ, runner or SubprocessRunner(), euid, sleep)
    except (EngineError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
