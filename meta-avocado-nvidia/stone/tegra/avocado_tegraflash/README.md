# avocado_tegraflash

This is a stdlib-only Python port of the Jetson stone provisioning script, started by a thin shim. The differential harness under `tests/parity` proves it equivalent to the frozen legacy script, case by case, for every profile entry.

Run it as `python -m avocado_tegraflash`. Pass `--prepare-only` to stop after the work directory is prepared, before anything is flashed.

The flash needs root. Without it the engine refuses before any USB action with:

```text
Run the same command again with sudo, keeping the environment and PATH:
  sudo -E env PATH="$PATH" <the command you just ran>
```

## Deviations from the legacy script

- `root-check-first`: the engine checks for root before any USB action; the frozen legacy script has no root check at all (only its scarthgap copy checks, and checks first).
- `absolute-cpp-wrapper`: the engine's cpp wrapper execs an absolute path, where the legacy script's execs a bare `cpp`.
- `unknown-profile-refused`: the engine refuses an unknown profile name and lists the five accepted names, where the legacy script takes its default branch and flashes NVMe.
- `one-board-only`: the engine refuses to flash unless exactly one board is in recovery mode, at the wait and again just before the flash, where the legacy script went ahead with whichever board the flash tool picked.
- `carrier-values-literal`: the engine writes carrier values literally, where the legacy script's sed substitution corrupts values containing `&` or backslash sequences.
- `boardctl-single-arguments`: the engine passes the boardctl target and serial as exactly one argument each, where the legacy script's unquoted expansion splits a value with whitespace.
- `prepare-only`: the engine can stop after preparing the work directory, where the legacy script always flashes.
- `symlink-destination-replaced`: the engine replaces a symlink at a copy destination, and copies a staged `boot.img` link before the boot image helper rewrites it, where the legacy script's plain `cp` and the helper write through the link (and `cp` fails on a dangling one, or creates its target as root).
- `env-key-missing-refused`: the engine refuses when `BOOTDEV`, `ROOTFS_DEVICE` or `EXTERNAL_ROOTFS_DRIVE` has no line in `.env.initrd-flash`, where the legacy script's `sed` changes nothing and the board flashes with the wrong boot device.
- `carrier-label-optional`: the engine proceeds when `carrier.env` has no `CARRIER_LABEL` line, where the legacy script aborts (its `grep` fails under `set -e` and `pipefail`, line 191).
- `mkbootimg-missing-refused`: the engine refuses, naming the cause, when `mkbootimg` is not on `PATH`, where the legacy script starts the boot image helper with an empty argument; a failing helper is likewise named by the engine and exits silently in the legacy script.
- `tos-name-bare-filename`: the engine refuses a `TOSIMGFILENAME` value that contains a slash or is `.` or `..`, naming the file and the value, where the legacy script uses the value as a path and `..` escapes the work directory.
- `layout-placeholder-unique`: the engine refuses a layout where `APPUUID` or `APPUUID_b` occurs other than exactly once, where the legacy script's `sed` fills every occurrence and two partitions get the same GUID.
- `carrier-value-shell-safe`: the engine refuses a carrier key that is not a shell identifier and a carrier value containing a double quote, dollar sign, backtick, backslash or newline, naming the key and the file, where the legacy script writes them into files that bash sources as root.
- `build-dir-locked`: the engine refuses to run while another provisioning run holds `<build dir>/tegraflash.lock`, where the legacy script has no lock and two runs restage one tree under each other.
- `env-file-missing-status`: a BSP without `.env.initrd-flash` makes the engine exit 1 with an error naming the file, where the legacy script exits 2.
- `recovery-pids-widened`: the engine counts the product ids 7819, 7919, 7026, 7226 and 7326 (the Thor and newer ids from the upstream finder and L4T) as recovery devices, so a board with one of them and no APX or RCM text is found, where the legacy script's `check_rcm` lists only ten ids.
- `cmdline-control-chars-refused`: the engine refuses a control character or newline in `AVOCADO_KERNEL_CMDLINE` or `AVOCADO_KERNEL_CMDLINE_EXTRA`, naming the variable, where the legacy script passes them to the root-run boot image helper.
