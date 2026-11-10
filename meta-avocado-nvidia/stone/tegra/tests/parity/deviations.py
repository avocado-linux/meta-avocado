"""Registry of intended differences between the oracle and the engine.

Every normalizer rule in compare.py that is not a pure environmental
difference (sandbox path, generated PARTUUIDs, wrapper temp dir) must name one
of these deviations. Adding a rule that hides a difference not listed here
widens the comparator and is forbidden.
"""

import re

DEVIATIONS = {
    "root-check-first": "the engine checks for root before any USB action; the frozen oracle has no root check",
    "absolute-cpp-wrapper": "the engine's cpp wrapper execs an absolute path; the oracle's execs a bare cpp",
    "unknown-profile-refused": "the engine refuses an unknown profile name and lists the five accepted names; the oracle takes its default branch and flashes NVMe",
    "one-board-only": "the engine pins exactly one board and refuses several; lsusb calls are not compared",
    "carrier-values-literal": "the engine writes carrier values literally; the oracle writes them through a sed substitution where & and backslash sequences are special, so such values are corrupted",
    "boardctl-single-arguments": "the engine passes the boardctl target and serial as exactly one argument each; the oracle uses an unquoted expansion, so a value with whitespace splits into several arguments",
    "prepare-only": "the engine can stop after preparing the work directory; the oracle always flashes",
    "symlink-destination-replaced": "the engine replaces a symlink at a copy destination, and copies a staged boot.img link before the boot image helper rewrites it; the oracle's plain cp and the helper write through the link (cp refuses a dangling one)",
    "env-key-missing-refused": "the engine refuses when BOOTDEV, ROOTFS_DEVICE or EXTERNAL_ROOTFS_DRIVE has no line in .env.initrd-flash; the oracle's sed passes silently and flashes with the wrong boot device",
    "carrier-label-optional": "the engine proceeds when carrier.env has no CARRIER_LABEL line; the oracle aborts there (grep fails under set -e and pipefail)",
    "mkbootimg-missing-refused": "the engine refuses, naming the cause, when mkbootimg is not on PATH, where the oracle starts the boot image helper with an empty argument; a failing helper is likewise named by the engine and exits silently in the oracle",
    "tos-name-bare-filename": "the engine refuses a TOSIMGFILENAME value containing a slash, or equal to . or .., naming the file and value; the oracle uses the value as a path, so .. escapes the work directory",
    "layout-placeholder-unique": "the engine refuses a layout where APPUUID or APPUUID_b occurs other than exactly once; the oracle's sed fills every occurrence, giving two partitions one GUID",
    "carrier-value-shell-safe": "the engine refuses a carrier key that is not a shell identifier and a carrier value containing a double quote, dollar sign, backtick, backslash or newline, naming the key and the file; the oracle writes them into files bash sources as root",
    "build-dir-locked": "the engine refuses to run while another provisioning run holds the lock on the same build directory; the oracle has no lock, so two runs restage one tree under each other",
    "env-file-missing-status": "a BSP without .env.initrd-flash makes the engine exit 1 with an error naming the file; the oracle exits 2",
    "recovery-pids-widened": "the engine counts the Thor and newer product ids 7819, 7919, 7026, 7226 and 7326 as recovery devices, so a board with one of them and no APX text is found; the oracle's check_rcm lists only ten ids",
    "cmdline-control-chars-refused": "the engine refuses a control character or newline in AVOCADO_KERNEL_CMDLINE or AVOCADO_KERNEL_CMDLINE_EXTRA, naming the variable; the oracle passes them to the root-run boot image helper",
    "required-image-refused": "the engine refuses, naming each file, when a manifest image it must flash (rootfs, var, initramfs, tegraflash_initramfs, tegraflash_esp, tegraflash_tos) is absent, not a regular file or empty; the oracle warns and flashes anyway",
    "partition-fit-refused": "the engine refuses, naming the image and the partition, when the rootfs or ESP image is larger than its partition in the layout the flash applies; the oracle flashes it anyway",
    "recovery-id-pinned": "the engine refuses a recovery device whose USB id is not in the manifest's rcm_ids, naming both ids; the oracle flashes whichever board it finds",
}

# Wrapper text rule for deviation absolute-cpp-wrapper: the two wrappers must
# be identical once the target of the final `exec` line is masked.
_EXEC_LINE = re.compile(r'^exec \S+ "\$@"$', re.MULTILINE)


def normalize_cpp_wrapper(text: str) -> str:
    """Mask the exec target of a cpp wrapper (deviation absolute-cpp-wrapper)."""
    return _EXEC_LINE.sub('exec <CPP> "$@"', text)


def cpp_wrapper_equivalent(oracle_text: str, engine_text: str) -> bool:
    """True when the wrappers differ at most in the exec target.

    Requires the exec line to be present in both so a wrapper with no exec
    line cannot compare equal by accident.
    """
    return (
        _EXEC_LINE.search(oracle_text) is not None
        and _EXEC_LINE.search(engine_text) is not None
        and normalize_cpp_wrapper(oracle_text) == normalize_cpp_wrapper(engine_text)
    )
