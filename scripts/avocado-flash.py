#!/usr/bin/env python3
"""Write a built Avocado OS image to a board, over whichever transport the
medium needs - and, separately, program its AHAB SRK hash fuses.

Backends are selected from the medium rather than hardcoded, so a board that
provisions over a different transport is a new backend rather than a new tool.

  sd        removable block device   fwup (default) or bmaptool
  emmc      USB serial download      uuu
  fuse-srk  serial console           one-time programmable fuses

Ported from the bash original. The port exists because `fuse-srk` has to hold a
conversation with U-Boot - send a command, wait for the prompt, parse what came
back, decide - and shell can only approximate that with sleeps. A tool whose job
is to refuse when preconditions are not met cannot be built on "slept six
seconds and hoped": a missed prompt means reading a stale buffer, and reading a
stale buffer means reporting blank fuses on a board whose fuses are not blank.

Every guard in here was written for a specific failure. The comments say which,
because without them a later reader trims what looks like defensive noise.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import struct
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

PROMPT = b"u-boot=> "

# i.MX93 SRK_HASH is 256 bits: bank 16, words 0-7. i.MX95 splits it across banks
# 16 and 17, so this is a per-SoC constant rather than a universal one.
SRK_FUSE_BANK = 16
SRK_FUSE_WORDS = 8
SPSDK_FAMILY = "mimx9352"


class Fatal(Exception):
    """Anything that should stop the tool with a message and no traceback."""


def info(msg: str) -> None:
    print(f"  {msg}")


# ---------------------------------------------------------------- resolution


def ancestors_of(path: Path):
    cur = path.resolve()
    while True:
        yield cur
        if cur.parent == cur:
            return
        cur = cur.parent


def resolve_deploy_dir(explicit: Path | None) -> Path:
    if explicit:
        return explicit.resolve()

    # Inside a bitbake or kas shell this is already the answer.
    builddir = os.environ.get("BUILDDIR")
    if builddir and (Path(builddir) / "tmp/deploy").is_dir():
        return (Path(builddir) / "tmp/deploy").resolve()

    # Collect every candidate at the nearest level that has any, then refuse if
    # there is more than one. Returning the first match made the choice
    # alphabetically: a workspace holding both build-imx93-frdm and
    # build-qemuarm64 resolved the i.MX93 tree for a caller who meant qemuarm64
    # and wrote that machine's fwup archive. The per-machine ambiguity guard
    # never fired, because the directory it landed on held exactly one machine.
    roots = [Path(__file__).resolve().parent.parent, *ancestors_of(Path.cwd())]
    for root in roots:
        found = set()
        for pattern in ("build*/build/tmp/deploy", "build/tmp/deploy", "tmp/deploy"):
            for cand in root.glob(pattern):
                if cand.is_dir():
                    # Resolve before de-duplicating: a `build` symlink pointing at
                    # the active build-<machine> directory is a common layout and
                    # matches two globs, which looked like two trees and tripped
                    # the refusal below over what is really one.
                    found.add(cand.resolve())
        if len(found) == 1:
            return found.pop()
        if len(found) > 1:
            listed = " ".join(sorted(str(f) for f in found))
            raise Fatal(
                f"several build trees under {root} ({listed}); pass --deploy to choose one"
            )

    raise Fatal("could not find a deploy directory; pass --deploy or set BUILDDIR")


def resolve_machine(deploy: Path, explicit: str | None) -> str:
    if explicit:
        return explicit
    env = os.environ.get("MACHINE")
    if env:
        return env

    dirs = sorted(d.name for d in (deploy / "images").glob("*") if d.is_dir())
    if len(dirs) == 1:
        return dirs[0]
    if not dirs:
        raise Fatal(f"no images found under {deploy}/images; pass --machine")
    raise Fatal(f"several machines built ({' '.join(dirs)}); pass --machine")


def resolve_fwup_archive(deploy: Path, machine: str) -> Path:
    """The fwup archive is produced by stone provision, not by stone bundle.

    A bundle-only rebuild refreshes os-bundle.aos and leaves this stale, so its
    age is reported rather than yesterday's bootloader being written silently.

    .img is deliberately not accepted: that is the unpacked raw image, which the
    bmaptool path takes. Handing it to fwup as an archive fails further in and
    less legibly than saying so here.
    """
    build = deploy / "stone/_build"
    found = [p for p in (build / f"{machine}-rootdisk.zip",
                         build / f"{machine}-rootdisk.fw") if p.is_file()]
    if len(found) == 1:
        return found[0]
    if not found:
        raise Fatal(
            f"no fwup archive for {machine} under {build}\n"
            f"  looked for: {machine}-rootdisk.zip, {machine}-rootdisk.fw\n"
            "  Not every machine produces a fwup archive. If this one deploys a raw\n"
            "  image instead, write it with --backend bmaptool; otherwise run the\n"
            "  provisioning step that builds the stone archive."
        )
    raise Fatal(
        f"several fwup archives for {machine} under {build} "
        f"({' '.join(str(f) for f in found)}); remove the stale one"
    )


def resolve_raw_image(deploy: Path, machine: str) -> Path:
    """Both globs are scoped to the machine.

    The second used to search the flat, shared stone/_build with no machine
    filter, so asking for a machine that had not been provisioned matched
    whatever *-rootdisk.img was there and wrote that machine's image to the card,
    while the error one line below claimed per-machine scoping.
    """
    for cand in sorted((deploy / "images" / machine).glob("*.wic")):
        if cand.is_file():
            return cand
    cand = deploy / "stone/_build" / f"{machine}-rootdisk.img"
    if cand.is_file():
        return cand

    # Name the producer. Nothing in the Yocto build writes this file, so a bare
    # "not found" reads as a broken build rather than a step not run.
    raise Fatal(
        f"no raw .wic or rootdisk.img found for {machine}\n"
        f"  expected: {deploy}/stone/_build/{machine}-rootdisk.img\n"
        "  produce it with the provisioning step that builds the stone archive, or\n"
        "  from an existing archive with:\n"
        f"    fwup -a -i {deploy}/stone/_build/{machine}-rootdisk.zip \\\n"
        f"         -d {deploy}/stone/_build/{machine}-rootdisk.img -t complete"
    )


# ------------------------------------------------------------- native tools


def find_native_sysroot(deploy: Path, tool: str) -> Path | None:
    """Backends are found in the build's native sysroots rather than assumed on
    the host: fwup is not packaged for most distributions, and the per-recipe
    component directories do not resolve their shared libraries because those
    live in sibling component trees. A recipe sysroot does resolve them.
    """
    top = Path(str(deploy).split("/deploy")[0])
    for sysroot in top.glob("work/*/avocado-stone/*/recipe-sysroot-native"):
        if (sysroot / "usr/bin" / tool).is_file() and os.access(sysroot / "usr/bin" / tool, os.X_OK):
            return sysroot
    return None


def native_tool_cmd(deploy: Path, tool: str, args: list[str]) -> list[str]:
    sysroot = find_native_sysroot(deploy, tool)
    if sysroot:
        # sudo drops LD_LIBRARY_PATH, so it is passed through env rather than
        # exported.
        return ["sudo", "env", f"LD_LIBRARY_PATH={sysroot}/usr/lib",
                str(sysroot / "usr/bin" / tool), *args]
    if shutil.which(tool):
        return ["sudo", tool, *args]
    raise Fatal(f"{tool} not found in the build sysroot or on PATH (run a build first)")


# ------------------------------------------------------------------- safety


def assert_safe_block_device(dev: str) -> None:
    """Refuse anything that is not an unmounted whole disk on a removable bus.

    fwup and bmaptool both rewrite the partition table from sector 0, so a
    mistyped letter destroys whatever it names with no prompt and no undo, and
    development hosts routinely carry multi-terabyte disks on the same /dev/sd*
    namespace as the card reader.

    Coarser than it looks in one direction: a USB enclosure holding a large disk
    is on a USB bus and passes. The retype-the-device prompt stands behind that.
    """
    p = Path(dev)
    if not p.exists() or not p.is_block_device():
        raise Fatal(f"not a block device: {dev}")

    # Resolve before deriving the sysfs name. /dev/disk/by-id and by-path entries
    # are symlinks, so they satisfy the block-device test while /sys/block/<link>
    # does not exist - which made the whole-disk check reject them as partitions.
    # Those are the names a board farm hands out, on the -y path that has no
    # prompt left to catch a mistake.
    resolved = p.resolve()
    if not Path("/sys/block") .joinpath(resolved.name).is_dir():
        raise Fatal(f"refusing a partition: pass the whole disk (e.g. /dev/sdb, not {dev})")

    # Ask udev which bus the device is on, rather than the kernel's removable
    # flag. That flag is wrong in both directions: drivers/mmc/core/block.c never
    # sets GENHD_FL_REMOVABLE, so an SD card in a native SDHCI reader reports
    # removable=0, while scsi_scan.c copies the SCSI RMB bit verbatim, so a USB
    # enclosure asserting RMB passed.
    #
    # ID_PATH rather than ID_BUS: ID_BUS is only set for ata/scsi/usb and is empty
    # on nvme, so keying on it would refuse an mmc device for want of a value.
    if not shutil.which("udevadm"):
        raise Fatal(
            f"refusing {dev}: udevadm is needed to identify the device's bus and was not found"
        )
    proc = subprocess.run(
        ["udevadm", "info", "--query=property", "--property=ID_PATH", "--value", str(resolved)],
        capture_output=True, text=True,
    )
    id_path = proc.stdout.strip() if proc.returncode == 0 else ""
    if not id_path:
        raise Fatal(f"refusing {dev}: udev reports no ID_PATH for it, so its bus cannot be established")
    if "-usb-" not in id_path and "mmc" not in id_path:
        raise Fatal(
            f"refusing {dev}: it is on '{id_path}', not a USB or MMC bus - "
            "pass a card reader, SD slot or USB stick"
        )

    # MOUNTPOINT is singular on purpose: the plural column arrived in util-linux
    # 2.37, and scarthgap's SANITY_TESTED_DISTROS still lists hosts on 2.32-2.36
    # where lsblk exits 1 with `unknown column: MOUNTPOINTS`. On those the guard
    # passed and fwup rewrote the partition table under a live mount. The exit
    # status is read rather than the pipeline's, so a failing lsblk refuses
    # instead of looking like "nothing is mounted".
    proc = subprocess.run(["lsblk", "-nro", "MOUNTPOINT", dev], capture_output=True, text=True)
    if proc.returncode != 0:
        raise Fatal(f"refusing {dev}: cannot read its mount state (lsblk failed)")
    if any(line.strip() for line in proc.stdout.splitlines()):
        subprocess.run(["lsblk", "-o", "NAME,SIZE,TYPE,RM,MOUNTPOINT", dev])
        raise Fatal(f"refusing {dev}: it has mounted partitions")


def confirm_destructive(target: str, payload: str | None, dry_run: bool, assume_yes: bool) -> None:
    """Ask before a destructive write, showing what is about to be written where.

    The payload is resolved by the caller first: the prompt used to come before
    that, so the retype gate - the only thing between a typo and a wiped disk -
    was cleared as a reflex before the tool had established it had anything to
    write at all.
    """
    if dry_run or assume_yes:
        return

    print(f"=== writing the whole OS to {target} (destructive) ===")
    if payload:
        print(f"  payload: {payload}")
    if Path(target).exists() and Path(target).is_block_device():
        subprocess.run(["lsblk", "-o", "NAME,SIZE,TYPE,RM,MODEL", target])
    print()
    reply = input("type the target again to confirm: ").strip()
    if reply != target:
        raise Fatal("mismatch, aborting")


def execute(cmd: list[str], dry_run: bool) -> None:
    if dry_run:
        print("dry-run: " + " ".join(cmd))
        return
    proc = subprocess.run(cmd)
    if proc.returncode != 0:
        raise Fatal(f"command failed with exit {proc.returncode}: {' '.join(cmd)}")


def finish(next_step: str, target: str, dry_run: bool) -> None:
    """Close out a write, or say plainly that none happened.

    Neither the sync nor the completion message used to be guarded, so a dry run
    printed "done. set the board's boot switches..." having written nothing: an
    operator powers the board, sees the previous image, and concludes the flash
    failed rather than that it never ran. sync is also a real syscall against
    every mounted filesystem, so running it broke the dry-run promise.
    """
    if dry_run:
        print(f"dry run: nothing was written to {target}.")
        return
    os.sync()
    print(f"done. {next_step}")


# ----------------------------------------------------------------- backends


def flash_fwup(deploy: Path, dev: str, archive: Path, task: str, dry_run: bool) -> None:
    mtime = datetime.fromtimestamp(archive.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
    info(f"archive: {archive} ({mtime})")
    info(f"task:    {task}")
    execute(native_tool_cmd(deploy, "fwup", ["-a", "-i", str(archive), "-d", dev, "-t", task]), dry_run)


def flash_bmaptool(deploy: Path, dev: str, image: Path, dry_run: bool) -> None:
    # Append, do not replace the extension. oe-core's image_types.bbclass emits
    # ${IMAGE_NAME}.${type}.bmap, i.e. <image>.wic.bmap - stripping .wic first
    # produced a name Yocto never writes, so every run took the --nobmap branch
    # and forfeited the per-region SHA256 verification this tool advertises.
    bmap = Path(str(image) + ".bmap")
    if not shutil.which("bmaptool"):
        raise Fatal("bmaptool not installed")

    info(f"image: {image}")
    if bmap.is_file():
        info(f"bmap:  {bmap} (per-region checksums verified)")
        cmd = ["sudo", "bmaptool", "copy", "--bmap", str(bmap), str(image), dev]
    else:
        # No --nobmap: let bmaptool look for itself, so a bmap this function did
        # not predict still gets used.
        info("no bmap beside the image - full copy, and no per-region verification")
        cmd = ["sudo", "bmaptool", "copy", str(image), dev]
    execute(cmd, dry_run)


def flash_uuu(deploy: Path, machine: str, dry_run: bool, assume_yes: bool) -> None:
    boot = deploy / "images" / machine / "imx-boot"
    if not boot.is_file():
        raise Fatal(f"no imx-boot for {machine}")
    image = resolve_raw_image(deploy, machine)

    # Pin the target instead of matching a vendor ID and hoping. `lsusb -d 1fc9:`
    # answers "is any NXP device in SDP mode", and uuu without -m then takes
    # whichever known device enumerated first - so with a second i.MX board on the
    # bench for an unrelated bisect, this wrote to that one.
    proc = subprocess.run(["lsusb"], capture_output=True, text=True)
    devices = []
    for line in proc.stdout.splitlines():
        m = re.search(r"Bus (\d+) Device (\d+): ID ((?:1fc9|15a2):[0-9a-f]{4})", line)
        if m:
            devices.append((f"{m.group(1)}:{m.group(2)}", m.group(3)))

    if not devices:
        raise Fatal("no NXP device in serial download mode (check the boot switches)")
    if len(devices) > 1:
        listed = "\n".join(f"  {p} {i}" for p, i in devices)
        raise Fatal(
            "several NXP devices in serial download mode:\n" + listed + "\n"
            "  uuu would take whichever enumerated first, so refusing rather than guessing.\n"
            "  Leave exactly one board in serial download mode."
        )
    usb_path, usb_id = devices[0]

    if not shutil.which("uuu"):
        raise Fatal("uuu not installed")

    info(f"bootloader: {boot}")
    info(f"image:      {image} ({image.stat().st_size // (1024 * 1024)} MiB)")
    info(f"usb path:   {usb_path} ({usb_id})")

    # The eMMC write is as destructive as the SD one and used to reach uuu with
    # no prompt at all, so -y was irrelevant on this path because nothing asked.
    confirm_destructive(usb_path, str(image), dry_run, assume_yes)

    # emmc_all, not emmc. Both built-ins default the image to the bootloader when
    # it is omitted, so `uuu -b emmc <boot>` wrote imx-boot into the eMMC boot
    # partition and nothing else - the board came back running whatever OS was
    # already on it, under a new bootloader, which looks like a successful flash.
    execute(["sudo", "uuu", "-m", usb_path, "-b", "emmc_all", str(boot), str(image)], dry_run)


# ------------------------------------------------------- reaching U-Boot


LOGIN_RE = re.compile(rb"login:\s*$")
SHELL_RE = re.compile(rb"[#$]\s*$")


def console_state(ub: "UBoot", settle: float = 3.0) -> str:
    """What is on the other end right now: 'uboot', 'login', 'shell' or 'unknown'.

    Nudges with a bare CR and classifies the reply. A CR is inert at all three -
    U-Boot reprints its prompt, a getty reprints the banner, a shell gives an
    empty line - so this cannot change the state it is measuring.
    """
    ub._drain(quiet=0.3)
    ub.ser.write(b"\r")
    out = b""
    deadline = time.monotonic() + settle
    while time.monotonic() < deadline:
        chunk = ub.ser.read(4096)
        if chunk:
            out += chunk
    tail = out.strip()[-200:]
    if PROMPT.strip() in out:
        return "uboot"
    if LOGIN_RE.search(tail):
        return "login"
    if SHELL_RE.search(tail):
        return "shell"
    return "unknown"


def interrupt_to_uboot(ub: "UBoot", window: float = 45.0) -> None:
    """Get the board to a U-Boot prompt, rebooting it if that is what it takes.

    The autoboot window is about three seconds and lands roughly ten seconds
    into a boot, so waiting and then knocking races it. Holding CR from the
    moment the reboot is issued does not: a CR at the U-Boot prompt only
    reprints the prompt, so over-sending costs nothing and under-sending loses
    the window and boots the OS instead.

    Rebooting through the console rather than over the network keeps this working
    on a board with no address yet, which is the state a freshly flashed card
    leaves it in.
    """
    state = console_state(ub)
    if state == "uboot":
        info("already at a U-Boot prompt")
        return

    if state == "login":
        info("board is at a login prompt; logging in to reboot it")
        ub.ser.write(b"root\r")
        # Wait for the shell rather than sleeping a fixed interval. A getty that
        # is slow to hand over swallows the reboot typed on top of it, and the
        # board then boots the OS while this holds CR at nothing - which reads as
        # "autoboot is disabled" and sends the next reader to bootdelay.
        got_shell = False
        seen = b""
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            seen += ub.ser.read(4096)
            seen = seen[-2048:]
            if SHELL_RE.search(seen.strip()[-200:]):
                got_shell = True
                break
            time.sleep(0.2)
        if not got_shell:
            raise Fatal(
                "logged in as root but no shell prompt appeared within 20s.\n"
                "  The console may require a password, which this does not handle - "
                "reboot the board yourself and re-run."
            )
        ub._drain(quiet=0.3)
        ub.ser.write(b"reboot\r")
    elif state == "shell":
        info("board is at a shell; rebooting it")
        ub.ser.write(b"reboot\r")
    else:
        # Nothing recognisable came back. It may be mid-boot, or wedged. A reset
        # from an unknown state is not something to do silently.
        raise Fatal(
            "could not tell what the board is doing - no U-Boot prompt, login "
            "prompt or shell responded.\n"
            "  It may be mid-boot; try again in a few seconds. If the console is "
            "silent, check that --port names the debug UART (P16 on the "
            "FRDM-IMX93) and not the OTG port."
        )

    info("holding the console through the autoboot window")
    seen = b""
    deadline = time.monotonic() + window
    while time.monotonic() < deadline:
        ub.ser.write(b"\r")
        time.sleep(0.1)
        # Accumulate rather than testing each read: at 115200 the prompt arrives
        # split across reads more often than not, and checking chunks in
        # isolation misses it entirely.
        seen += ub.ser.read(4096)
        seen = seen[-4096:]
        if PROMPT in seen:
            # Drain the CRs still in flight so the caller starts on a clean prompt.
            ub._drain(quiet=0.5)
            ub.sync()
            info("at a U-Boot prompt")
            return

    raise Fatal(
        f"the board did not stop at a U-Boot prompt within {window:.0f}s.\n"
        "  autoboot may be disabled, or bootdelay set to 0 - check `bootdelay` in "
        "the environment."
    )


# --------------------------------------------------------------------- ums


def block_devices() -> set[str]:
    return {p.name for p in Path("/sys/block").iterdir()}


def usb_gadget_present() -> bool:
    """Is the board currently enumerated as a USB device?

    U-Boot's UMS exports through the SoC's download gadget (1fc9 on NXP), and
    Linux's own file-storage gadget uses 0525:a4a5. Checking this separates
    "nothing is plugged in" from "it is plugged in but exported nothing", which
    are different problems with the same symptom.
    """
    proc = subprocess.run(["lsusb"], capture_output=True, text=True)
    if proc.returncode != 0:
        return False
    return bool(re.search(r"ID (1fc9|15a2|0525):", proc.stdout))


def ums_expose(ub: "UBoot", controller: int, dev: str, timeout: float = 25.0) -> str:
    """Ask U-Boot to export a medium as USB mass storage and find it on the host.

    The board keeps the card; the reader moves. `ums` blocks in U-Boot for as long
    as it is exporting, so this does not wait for a prompt afterwards - it watches
    /sys/block instead.

    The new device is identified by diffing before against after, never by taking
    the highest /dev/sd* or the newest by mtime. A development host carries
    multi-terabyte disks in the same namespace, and this path ends in a write that
    rewrites the partition table from sector 0.
    """
    # Release first, and wait for the device to go. An export left running by an
    # earlier invocation is already in `before`, so re-exporting it produces no
    # new name and the diff below reports "nothing appeared" while the device is
    # sitting right there - a false negative that blames the cable.
    if usb_gadget_present():
        info("a UMS export is already running; releasing it first")
        ums_release(ub, quiet=True)
        gone = time.monotonic() + 15
        while time.monotonic() < gone and usb_gadget_present():
            time.sleep(0.5)

    before = block_devices()

    # ums does not return, so fire it and watch the host rather than the console.
    ub._drain(quiet=0.2)
    ub.ser.write(f"ums {controller} {dev}\r".encode())

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        time.sleep(0.5)
        new = block_devices() - before
        # Ignore loop/ram devices that can appear for unrelated reasons.
        new = {n for n in new if not n.startswith(("loop", "ram", "zram"))}
        if len(new) == 1:
            name = new.pop()
            # Let partitions settle before anything reads them.
            time.sleep(2)
            return f"/dev/{name}"
        if len(new) > 1:
            raise Fatal(
                "several new block devices appeared while exporting UMS "
                f"({' '.join(sorted(new))}); refusing rather than guessing which is "
                "the board"
            )

    # Distinguish "nothing enumerated" from "enumerated but no block device", so
    # the message names what was actually observed rather than guessing at a cable.
    if usb_gadget_present():
        raise Fatal(
            f"the board enumerated a USB gadget but no new block device appeared "
            f"within {timeout:.0f}s of 'ums {controller} {dev}'.\n"
            "  The cable and port are fine. Check that the medium exists - 'mmc list'\n"
            "  at the U-Boot prompt names which index is the SD card."
        )
    raise Fatal(
        f"no USB gadget and no new block device appeared within {timeout:.0f}s of "
        f"'ums {controller} {dev}'.\n"
        "  On the FRDM-IMX93 the OTG port is P2 (USB2.0 Type-C, 'host and device\n"
        "  controller (USB 1) of target' in UM12181). P1 is power-delivery only and\n"
        "  carries no data; P16 is the CH342F debug console. A cable in either of\n"
        "  those enumerates nothing here."
    )


def unmount_all(dev: str) -> None:
    """Drop any partitions udisks auto-mounted the moment the device appeared.

    Writing under a live mount is what the block-device guard exists to prevent,
    and on this path the host mounts the device itself a second after U-Boot
    exports it.
    """
    proc = subprocess.run(["lsblk", "-nro", "NAME,MOUNTPOINT", dev],
                          capture_output=True, text=True)
    for line in proc.stdout.splitlines():
        parts = line.split(None, 1)
        if len(parts) == 2 and parts[1].strip():
            target = f"/dev/{parts[0]}"
            info(f"unmounting {target} from {parts[1].strip()}")
            subprocess.run(["udisksctl", "unmount", "-b", target],
                           capture_output=True, text=True)


def ums_release(ub: "UBoot", quiet: bool = False) -> None:
    """Ctrl-C is how ums is stopped; U-Boot returns to its prompt afterwards."""
    try:
        ub.ser.write(b"\x03")
        time.sleep(1)
        ub.sync()
    except Fatal:
        # Worth reporting but not worth failing a completed write over.
        if not quiet:
            info("note: the board did not return to a U-Boot prompt after releasing UMS")


# ---------------------------------------------------------------- fuse-srk


class UBoot:
    """A U-Boot console that synchronises on the prompt rather than on sleep.

    pyserial rather than hand-rolled termios because this needs timeouts and
    framing, not just a file descriptor. It is imported lazily so that flashing -
    which needs no serial at all - keeps working without the dependency.
    """

    def __init__(self, port: str, timeout: float = 10.0):
        try:
            import serial  # noqa: PLC0415
        except ImportError as exc:
            raise Fatal(
                "pyserial is required for fuse-srk (flashing does not need it).\n"
                "  Install it with your distribution's python-pyserial package, or\n"
                "  run this tool with SPSDK's interpreter, which already ships it."
            ) from exc

        self.timeout = timeout
        self.ser = serial.Serial(port, baudrate=115200, timeout=0.2)

    def close(self) -> None:
        self.ser.close()

    def _drain(self, quiet: float = 0.3) -> None:
        last = time.monotonic()
        while time.monotonic() - last < quiet:
            if self.ser.in_waiting and self.ser.read(self.ser.in_waiting):
                last = time.monotonic()

    def _read_until(self, needle: bytes, timeout: float) -> bytes:
        out = b""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            chunk = self.ser.read(4096)
            if chunk:
                out += chunk
                if needle in out:
                    return out
        raise Fatal(
            f"timed out waiting for the U-Boot prompt after {timeout:.0f}s.\n"
            f"  Read so far: {out.decode('latin-1')[-400:]!r}\n"
            "  The board must be sitting at a U-Boot prompt - interrupt autoboot first."
        )

    def sync(self) -> None:
        self._drain()
        self.ser.write(b"\r")
        self._read_until(PROMPT, self.timeout)

    def cmd(self, command: str, timeout: float | None = None) -> str:
        self._drain(quiet=0.2)
        self.ser.write(command.encode() + b"\r")
        raw = self._read_until(PROMPT, timeout or self.timeout)
        text = raw.decode("latin-1").replace("\r", "")
        lines = [ln for ln in text.split("\n") if ln.strip() != "u-boot=>"]
        if lines and command in lines[0]:
            lines = lines[1:]
        return "\n".join(lines).strip()


def spsdk_tool(name: str, bindir: Path | None) -> Path:
    if bindir:
        p = bindir / name
        if not p.exists():
            raise Fatal(f"{name} not found at {p}")
        return p
    found = shutil.which(name)
    if not found:
        raise Fatal(f"{name} not on PATH; install SPSDK or pass --spsdk-bin")
    return Path(found)


def run_checked(cmd: list[str]) -> str:
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise Fatal(f"{' '.join(cmd)} failed:\n{proc.stdout}\n{proc.stderr}")
    return proc.stdout


def srk_certs(keys: Path, key_type: str) -> list[Path]:
    certs = [keys / "crts" / f"SRK{i}_{key_type}_cert.pem" for i in range(4)]
    missing = [c for c in certs if not c.exists()]
    if missing:
        raise Fatal(
            "missing SRK certificates:\n  " + "\n  ".join(str(m) for m in missing)
            + "\nExpected a tree as produced by 'nxpcrypto pki-tree ahab'."
        )
    return certs


def compute_fuse_words(nxpcrypto: Path, certs: list[Path], workdir: Path) -> list[int]:
    out_bin = workdir / "srk_fuse.bin"
    cmd = [str(nxpcrypto), "rot", "calculate-hash", "-f", SPSDK_FAMILY]
    for c in certs:
        cmd += ["-k", str(c)]
    cmd += ["-o", str(out_bin)]
    run_checked(cmd)

    raw = out_bin.read_bytes()
    expected = SRK_FUSE_WORDS * 4
    if len(raw) != expected:
        raise Fatal(
            f"expected a {expected}-byte SRK hash for {SPSDK_FAMILY}, got {len(raw)}.\n"
            "  i.MX 8/8x use a 512-bit hash and 9x uses 256-bit; a mismatch here means\n"
            "  the wrong family was selected, and copying the i.MX8 srktool invocation\n"
            "  is exactly how that happens."
        )

    # LITTLE-endian, and this is not a style choice. NXP's
    # doc/imx/ahab/guides/mx8ulp_9x_secure_boot.txt section 1.6 dumps the fuse
    # file with `od -t x4` - native byte order, no --endian=big - and programs
    # those words verbatim:
    #
    #     $ od -t x4 SRK_1_2_3_4_fuse.bin
    #     0000000 db2959f2 90dfc39c ...
    #     => fuse prog 16 0 0xdb2959f2
    #
    # introduction_ahab.txt shows the same file under `od -t x4 --endian=big`,
    # but only to demonstrate that its contents equal the SHA - and says outright
    # "The commands above cannot be used as reference to program the SoC
    # SRK_HASH fuses". Reading big-endian here burns the hash byte-swapped. That
    # happened on 2026-08-13: every guard in this tool passed, because they all
    # check what was intended rather than what NXP specifies, and the fuses are
    # one-time programmable so the board can no longer validate AHAB at all.
    return list(struct.unpack("<8I", raw))


def read_fuse_words(ub: UBoot) -> list[int]:
    out = ub.cmd(f"fuse read {SRK_FUSE_BANK} 0 {SRK_FUSE_WORDS}")
    words: list[int] = []
    for line in out.split("\n"):
        m = re.match(r"\s*Word 0x[0-9a-fA-F]+:\s*(.*)$", line)
        if m:
            words += [int(w, 16) for w in m.group(1).split()]
    if len(words) != SRK_FUSE_WORDS:
        raise Fatal(
            f"could not parse {SRK_FUSE_WORDS} fuse words from:\n{out}\n"
            "Refusing to program fuses without knowing their current value."
        )
    return words


def read_lifecycle(ub: UBoot) -> str:
    out = ub.cmd("ahab_status", timeout=15)
    m = re.search(r"Lifecycle:\s*0x[0-9a-fA-F]+,\s*(.+)", out)
    if not m:
        raise Fatal(f"could not read lifecycle from ahab_status:\n{out}")
    return m.group(1).strip()


def fuse_srk(args, deploy: Path, machine: str) -> None:
    """Program the SRK hash, or refuse to.

    Does NOT implement ahab_close. Closing is what makes the ROM refuse unsigned
    images and is the step that can leave a board unable to boot anything you
    have; burning the hash while the part stays OEM Open is recoverable in the
    sense that matters, because an open part boots regardless of the
    authentication verdict. Close is absent rather than gated, so it cannot be
    reached by mistyping this tool's arguments.
    """
    nxpimage = spsdk_tool("nxpimage", args.spsdk_bin)
    nxpcrypto = spsdk_tool("nxpcrypto", args.spsdk_bin)

    print("\n== Host-side checks")
    boot = (deploy / "images" / machine / "imx-boot")
    if not boot.exists():
        raise Fatal(f"no imx-boot under {deploy / 'images' / machine}")
    boot = boot.resolve()

    out = run_checked([str(nxpimage), "ahab", "info", "-f", SPSDK_FAMILY, "-b", str(boot)])
    if "Signed by OEM keys" not in out:
        raise Fatal(
            f"{boot} is not OEM-signed. Fusing an SRK hash for an unsigned bootloader "
            "would burn a root of trust nothing on this card uses."
        )
    info(f"{boot.name}: OEM-signed")

    if not args.keys:
        raise Fatal("--keys is required for fuse-srk")
    certs = srk_certs(args.keys, args.key_type)
    info(f"SRK certificates: {certs[0].parent}")

    workdir = Path(os.environ.get("TMPDIR", "/tmp")) / "avocado-fuse-srk"
    workdir.mkdir(parents=True, exist_ok=True)
    words = compute_fuse_words(nxpcrypto, certs, workdir)
    info("SRK hash: " + " ".join(f"{w:08X}" for w in words))

    print("\n== Board-side checks")
    ub = UBoot(args.port)
    try:
        if getattr(args, "interrupt", False):
            interrupt_to_uboot(ub)
        else:
            ub.sync()
            info("at a U-Boot prompt")

        lifecycle = read_lifecycle(ub)
        info(f"lifecycle: {lifecycle}")
        if "OEM Open" not in lifecycle:
            raise Fatal(
                f"lifecycle is {lifecycle!r}, not 'OEM Open'. This tool only programs "
                "fuses on an open part."
            )

        current = read_fuse_words(ub)
        info("current fuses: " + " ".join(f"{w:08X}" for w in current))
        if any(current):
            raise Fatal(
                "SRK hash fuses are not blank. They are one-time programmable, so a\n"
                "  partially burned field cannot be corrected - refusing.\n"
                "  current:  " + " ".join(f"{w:08X}" for w in current) + "\n"
                "  intended: " + " ".join(f"{w:08X}" for w in words)
            )
        info("fuses are blank")

        commands = [f"fuse prog -y {SRK_FUSE_BANK} {i} 0x{w:08X}" for i, w in enumerate(words)]

        print("\n== Fuse program commands")
        for c in commands:
            print(f"  {c}")

        if not args.commit:
            print(
                "\nDry run: nothing was programmed. Re-run with --commit to burn.\n"
                "Burning leaves the part OEM Open, so the board still boots whatever the\n"
                "authentication verdict is. Closing the device is a separate step and\n"
                "this tool does not implement it."
            )
            return

        print("\n== Irreversible")
        print(
            "  These fuses are one-time programmable. If the private keys behind this\n"
            "  hash are lost, nothing can ever be signed for this board again.\n"
            f"  Back up {args.keys} before continuing."
        )
        typed = input(f"  Type the machine name to proceed [{machine}]: ").strip()
        if typed != machine:
            raise Fatal("confirmation did not match; nothing was programmed")

        print("\n== Programming")
        for c in commands:
            out = ub.cmd(c, timeout=15)
            if out:
                info(out.replace("\n", " ")[:120])

        print("\n== Verifying")
        after = read_fuse_words(ub)
        info("fuses now: " + " ".join(f"{w:08X}" for w in after))
        if after != words:
            raise Fatal(
                "read-back does not match the intended SRK hash.\n"
                "  intended: " + " ".join(f"{w:08X}" for w in words) + "\n"
                "  actual:   " + " ".join(f"{w:08X}" for w in after)
            )
        info("read-back matches")

        # Read the ELE's verdict rather than stopping at "the words I meant are
        # the words I wrote". Every check above compares the burn against this
        # tool's own intent, so all of them pass on a hash that is correctly
        # written and wrong - which is precisely what a byte-swapped hash is. The
        # event log is per boot session and the entries still present now were
        # produced before the fuses existed, so this has to reboot to mean
        # anything.
        print("\n== Confirming with the ELE")
        info("rebooting to read a fresh event log")
        interrupt_to_uboot(ub)
        status = ub.cmd("ahab_status", timeout=25)
        print(status)

        if "FAILURE_IND" in status or "BAD_KEY_HASH" in status:
            raise Fatal(
                "the fuses were programmed and read back correctly, but the ELE still\n"
                "  reports authentication events on a fresh boot. The value written does\n"
                "  not match what the ELE computes for this image.\n"
                "\n"
                "  The board is NOT bricked: it is OEM Open, so it boots regardless. Do\n"
                "  NOT close it - with a hash the ELE rejects, closing makes it refuse\n"
                "  every image you can sign.\n"
                "\n"
                "  SRK_HASH is one-time programmable, so this board can no longer\n"
                "  validate AHAB. Check byte order first: NXP programs the words as\n"
                "  `od -t x4` prints them (native), not `od -t x4 --endian=big`."
            )

        info("no authentication events - the fused hash matches this image")
        print(
            "\nThe part is still OEM Open, so signature failures are logged rather than\n"
            "fatal. Closing is a separate step and this tool does not implement it."
        )
    finally:
        ub.close()


# --------------------------------------------------------------------- main


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="avocado-flash",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description="Write a built Avocado OS image to a board, or program its SRK fuses.",
        epilog="""\
media:
  sd        removable block device (SD card, USB stick); needs a device
  emmc      on-board eMMC over USB serial download
  ums       flash the board's own card in place. U-Boot exports it as USB mass
            storage, so the card never leaves the slot. Needs the board at a
            U-Boot prompt and a cable on the SoC's OTG port - on the FRDM-IMX93
            that is P2, not the power-only P1 or the debug P16.
  fuse-srk  program the AHAB SRK hash over the serial console. Never reachable
            from sd/emmc: flashing is repeatable, fuses are not.

backends:
  fwup      writes the stone fwup archive. The default for 'sd' because it is the
            only backend that evaluates the manifest, so partitions marked expand
            grow to fill the medium.
  bmaptool  writes a raw .wic/.img, skipping unmapped blocks and verifying a
            SHA256 per mapped region.
  uuu       NXP serial-download protocol; the board must already be in serial
            download mode.

examples:
  avocado-flash sd /dev/sdb
  avocado-flash --machine avocado-imx93-frdm sd /dev/sdb
  avocado-flash emmc
  avocado-flash -k ~/ahab-keys fuse-srk
""",
    )
    ap.add_argument("-m", "--machine", help="Avocado machine (default: $MACHINE, else autodetect)")
    ap.add_argument("-d", "--deploy", type=Path, help="deploy directory (default: autodetect)")
    ap.add_argument("-b", "--backend", choices=["fwup", "bmaptool", "uuu"])
    ap.add_argument("-t", "--task", default="complete",
                    help="fwup task: complete (whole medium, including var) or "
                         "upgrade (inactive A/B slots only, var untouched)")
    ap.add_argument("-n", "--dry-run", action="store_true", help="print what would run; touch nothing")
    ap.add_argument("-y", "--assume-yes", action="store_true",
                    help="skip the confirmation. For a board farm, not interactive use")
    # fuse-srk only
    ap.add_argument("-p", "--port", default="/dev/ttyACM0", help="serial console (fuse-srk)")
    ap.add_argument("-k", "--keys", type=Path, help="AHAB PKI tree (fuse-srk)")
    ap.add_argument("--key-type", default="secp384r1")
    ap.add_argument("--spsdk-bin", type=Path, help="directory holding nxpimage/nxpcrypto")
    ap.add_argument("--commit", action="store_true",
                    help="fuse-srk: actually program the fuses (irreversible)")
    ap.add_argument("--interrupt", action="store_true",
                    help="get the board to a U-Boot prompt first, rebooting it "
                         "through the console if it is running Linux")
    ap.add_argument("--ums-dev", default="mmc 1",
                    help="what U-Boot exports for 'ums' (default: %(default)s; "
                         "'mmc list' names which is the SD)")
    ap.add_argument("--usb-controller", type=int, default=0,
                    help="USB controller index for 'ums' (default: %(default)s)")
    ap.add_argument("medium", choices=["sd", "emmc", "ums", "fuse-srk"])
    ap.add_argument("device", nargs="?", help="block device for 'sd'")
    return ap


def main() -> int:
    args = build_parser().parse_args()

    deploy = resolve_deploy_dir(args.deploy)
    machine = resolve_machine(deploy, args.machine)
    print(f"machine: {machine}")
    print(f"deploy:  {deploy}")

    # Only fwup evaluates the manifest's tasks. Refusing rather than ignoring the
    # flag matters because the two differ in whether /var survives: a --task
    # upgrade silently downgraded to a whole-medium write destroys the state the
    # caller asked to keep, and the write looks successful either way.
    if args.task != "complete" and args.backend not in (None, "fwup"):
        raise Fatal(f"--task applies to the fwup backend only (got backend '{args.backend}')")
    if args.task != "complete" and args.medium != "sd":
        raise Fatal(f"--task applies to the fwup backend only (medium '{args.medium}')")

    if args.medium == "sd":
        if not args.device:
            raise Fatal("'sd' needs a device (see --help)")
        assert_safe_block_device(args.device)

        # Resolve the payload before asking, and show it in the prompt: clearing
        # the retype gate before the tool knows it has anything to write trains
        # people to clear it by reflex.
        backend = args.backend or "fwup"
        if backend == "fwup":
            payload = resolve_fwup_archive(deploy, machine)
        elif backend == "bmaptool":
            payload = resolve_raw_image(deploy, machine)
        else:
            raise Fatal(f"backend {backend} cannot write a block device")

        confirm_destructive(args.device, str(payload), args.dry_run, args.assume_yes)

        if backend == "fwup":
            flash_fwup(deploy, args.device, payload, args.task, args.dry_run)
        else:
            flash_bmaptool(deploy, args.device, payload, args.dry_run)
        finish("set the board's boot switches to the SD position and power on.",
               args.device, args.dry_run)

    elif args.medium == "ums":
        if args.device:
            raise Fatal(
                f"ums discovers the device itself (got {args.device}); it is the whole "
                "point of the verb that the card does not move"
            )
        payload = resolve_fwup_archive(deploy, machine)

        ub = UBoot(args.port)
        target = None
        try:
            if args.interrupt:
                interrupt_to_uboot(ub)
            else:
                ub.sync()
                info("at a U-Boot prompt")
            info(f"exporting {args.ums_dev} over USB controller {args.usb_controller}")
            target = ums_expose(ub, args.usb_controller, args.ums_dev)
            info(f"board appeared as {target}")

            unmount_all(target)
            # The same guard the sd path uses. The device is on a USB bus here, so
            # this passes - but it also catches a mount that reappeared and the
            # case where the discovered node is somehow a partition.
            assert_safe_block_device(target)

            confirm_destructive(target, str(payload), args.dry_run, args.assume_yes)
            flash_fwup(deploy, target, payload, args.task, args.dry_run)
            finish("power-cycle the board; the card was never removed.",
                   target, args.dry_run)
        finally:
            if target:
                os.sync()
            ums_release(ub)
            ub.close()

    elif args.medium == "emmc":
        backend = args.backend or "uuu"
        if backend != "uuu":
            raise Fatal(f"backend {backend} cannot write over serial download")
        flash_uuu(deploy, machine, args.dry_run, args.assume_yes)
        finish("set the board's boot switches to the eMMC position and power on.",
               "the board", args.dry_run)

    else:
        if args.device:
            raise Fatal(f"fuse-srk takes no device argument (got {args.device})")
        fuse_srk(args, deploy, machine)

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Fatal as exc:
        print(f"avocado-flash: {exc}", file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        print("\ninterrupted", file=sys.stderr)
        sys.exit(130)
