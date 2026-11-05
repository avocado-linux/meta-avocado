# avocado_tegraflash

This is a stdlib-only Python port of the Jetson stone provisioning script, started by a thin shim. The differential harness under `tests/parity` proves it equivalent to the frozen legacy script, case by case, for every profile entry.

Run it as `python -m avocado_tegraflash`. Pass `--prepare-only` to stop after the work directory is prepared, before anything is flashed.

## Deviations from the legacy script

- `root-check-first`: the engine checks for root before any USB action, where the legacy script checks later.
- `absolute-cpp-wrapper`: the engine's cpp wrapper execs an absolute path, where the legacy script's execs a bare `cpp`.
- `unknown-profile-refused`: the engine refuses an unknown profile name and lists the five accepted names, where the legacy script takes its default branch and flashes NVMe.
- `one-board-only`: the engine pins exactly one board and refuses several, so `lsusb` calls are not compared.
- `carrier-values-literal`: the engine writes carrier values literally, where the legacy script's sed substitution corrupts values containing `&` or backslash sequences.
- `boardctl-single-arguments`: the engine passes the boardctl target and serial as exactly one argument each, where the legacy script's unquoted expansion splits a value with whitespace.
- `prepare-only`: the engine can stop after preparing the work directory, where the legacy script always flashes.

## Known differences that are not listed deviations

- A `carrier.env` with no `CARRIER_LABEL` line no longer aborts silently: the legacy script aborts there under `set -e` and `pipefail` (line 191), and the engine does not port that.
- `EXTERNAL_ROOTFS_DRIVE` is written unquoted, exactly as the legacy script writes it.
- A stock `DefaultBootPriority` value ending in a comma keeps its trailing empty field.
- A missing `mkbootimg`, or a failing boot image helper, raises an error naming the cause where the legacy script exited silently.
