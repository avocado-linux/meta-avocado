# Winding down the `avocado-flash nvme` host wrapper

This is the migration plan for removing the host wrapper for Jetson Orin Nano
once the engine carries every guard the wrapper carries today. Nothing in this
change deletes the wrapper. Removal is a follow-up change, gated on section 5.

## 1. Why

On 2026-11-10 the team decided to consolidate provisioning on avocado-cli:
`avocado provision` is the one supported way to write a board. Both doors
already run one engine. `avocado-flash nvme` runs
`stone-provision-tegraflash.sh` from the deploy tree, `avocado provision` runs
it from the stone output directory, and that script starts the Python engine in
`meta-avocado-nvidia/stone/tegra/avocado_tegraflash/`. What differed was the
guards: the wrapper refused things the engine did not. This change closes that
gap so the wrapper can go.

## 2. What moved into the engine in this change

Each line is the engine module and the deviation name used in the parity
record (`meta-avocado-nvidia/stone/tegra/tests/parity/deviations.py`).

- `required-image-refused`: `staging.py` refuses a missing or empty required image before any erase. `tegraflash_tos` stays a mandatory image key.
- `partition-fit-refused`: `fit.py` refuses an image larger than its partition before any erase.
- `recovery-id-pinned`: `recovery.py`, driven by the manifest's `tegraflash.rcm_ids`, refuses a different Jetson in recovery and names both ids. The Orin Nano manifest declares only 7523; 7623 (the 4GB module) is not pinned because no board with that id was ever run on hardware: pinning an unobserved sibling would refuse a valid board and would ship an id nobody has seen.
- `cmdline-control-chars-refused`: `env.py` refuses a kernel command line carrying control characters.
- `device-confirmation`: `confirm.py` asks the operator to retype the target before writing, and the prompt names every medium the erase flags destroy, including the profile medium's device node, emmc when the flash would erase it, QSPI and UEFI variables; `AVOCADO_PROVISION_FORCE=1` skips it.
- upstream-drift record: `meta-avocado-nvidia/stone/tegra/upstream-tracking.json`, checked by `meta-avocado-nvidia/stone/tegra/tests/test_upstream_drift.py`.

### 2.1 Release notes

- `AVOCADO_FLASH_LAUNCHER=1` opts `avocado-flash` into the new launcher (`scripts/avocado_flash_launch/`), which covers sd, emmc, ums and nvme and runs the stone profile instead of the Python board tables. It is opt-in in this change; flipping it to the default is planned by this change's later work, and the registry and wrapper stay until then.
- A named device no longer skips the retype. Before, passing an explicit device meant no confirmation. Now only `AVOCADO_PROVISION_FORCE=1` skips it. With no terminal and no signal the run proceeds with a notice; `AVOCADO_PROVISION_FORCE=0` with no terminal refuses; any value other than 1 or 0 refuses. The full table is `meta-avocado-distro/stone/tests/confirm-vectors.tsv`, shared by the shell library and the engine (`avocado_tegraflash/confirm.py`, `decide_confirmation`).
- New variables: `AVOCADO_PROVISION_DRY_RUN=1` (run every guard, change nothing), `AVOCADO_PROVISION_RCM_ID`, `AVOCADO_PROVISION_ALLOW_UNPINNED_KERNEL=1`, `AVOCADO_PROVISION_FWUP_TASK` (only `complete` is accepted by the ums profile), `AVOCADO_PROVISION_HOST_MOUNTS` (a mount table exported by avocado-cli, read as a second table), and `AVOCADO_FLASH_LAUNCHER`.
- The engine refuses a board nothing identifies, an unpinned kernel, and a `PATH` with relative entries is cleaned; see section 3.

## 3. Wrapper-only guards: status

Six guards lived only in the wrapper. This change moves three into the engine
(3.1, 3.3, 3.5), meets one in the launcher (3.6), and leaves two as follow-ups
that still block removal (3.2, 3.4). The options for the open two are listed;
this document does not pick one.

### 3.1 PATH hardening - moved into the engine

Was: `scripts/avocado_flash_tegra/plan.py`, `safe_path()`, kept only the
absolute components of the caller's `PATH` before running the script as root,
because an empty or relative component means the current directory, which is
the deploy directory.

Now: `meta-avocado-nvidia/stone/tegra/avocado_tegraflash/cli.py` (`_run`)
replaces `PATH` with its absolute components (`_absolute_path`) before the
engine resolves any tool, so the guard holds through `avocado provision` too.

### 3.2 Per-run log file - follow-up, still open

Today: `scripts/avocado_flash_tegra/runner.py`, `stream()`, tees the script's
output to a log file for each run, so a failed flash leaves a record. This
change does not move it.

Decision, one of:

- Move into the engine: the engine's `runner.py` writes a per-run log.
- Move to avocado-cli: `avocado provision` captures and keeps the output.
- Drop: rely on the terminal scrollback.

### 3.3 Refusing a run with no pinned kernel - moved into the engine

Was: the wrapper required the kernel `Image` in the deploy tree; the engine
only warned and took the prebuilt `boot.img`.

Now: `avocado_tegraflash/cli.py` (`_run`) refuses when no kernel is pinned,
naming the cause. `AVOCADO_PROVISION_ALLOW_UNPINNED_KERNEL=1` (exactly `1`)
accepts the prebuilt boot image explicitly.

### 3.4 The confirmed board is not pinned to the flash - follow-up, still open

Today the wrapper has an operator retype the board's `bus:device`, then runs
the engine with `AVOCADO_PROVISION_FORCE=1` and passes it no device identity.
The engine stages for minutes, waits for a recovery device, and checks that one
board is still there before the flash. That check compares only against the
engine's own wait, so a board of the same model swapped in during staging is
flashed without the operator confirming it. `./initrd-flash` is also run with
only the erase flags, so the tool chooses its device itself and the engine's
choice is advisory. Under `avocado provision` the engine prompts after its
wait, so staging is not exposed there; only the gap between the recheck and the
tool's own enumeration remains. This change does not close it.

Decision, one of:

- Move into the engine: accept the confirmed `bus:device` in a new variable, refuse in the wait and the recheck unless it matches, and pass the device to `initrd-flash` if the tool takes an instance argument.
- Move to avocado-cli: `avocado provision` confirms and passes the identity through.
- Drop: accept that a swap during staging is the operator's responsibility.

### 3.5 Refusing a machine with no recorded recovery id - moved into the engine

Was: `scripts/avocado_flash_tegra/rcm.py`, `expected_rcm_id()`, raised
`FlashError` for a machine with no recorded recovery-mode USB id. The engine
only logged and proceeded.

Now: `avocado_tegraflash/cli.py` (the check before staging) refuses when the
manifest declares no `rcm_ids` and `AVOCADO_PROVISION_RCM_ID` is not set, in the
cases where the confirmation would be skipped (`AVOCADO_PROVISION_FORCE=1`, or
an unattended run). With a terminal it prints a warning and relies on the
retyped confirmation. `AVOCADO_PROVISION_RCM_ID=<vendor:product>` supplies the
id for a board whose manifest declares none. Recovery ids and their evidence
live only in the stone manifest (`rcm_ids`, `rcm_evidence`); the launcher's
`boards` verb (`scripts/avocado_flash_launch/boards.py`) lists them.

### 3.6 Work directory ownership and mode refusals - met by the launcher

Was: `scripts/avocado_flash_tegra/workdir.py` refused a work directory that
another user could pre-create or write, because the helper staged there runs as
root.

Now: the launcher creates its inputs in a private scratch directory
(`scripts/avocado_flash_launch/scratch.py`): mode 0700, owned by the caller,
carrying a marker with a random token, and removed only if the marker matches.
This protects runs started through the launcher. The engine itself still has no
such check on its own work directory, so a run through `avocado provision` that
passes a shared directory is not covered; that stays with avocado-cli.

## 4. Removal list

Every path below was checked to exist in this tree.

- [ ] `scripts/avocado_flash_tegra/`
- [ ] `scripts/avocado_flash_boards/`, together with the `boards` dispatch in `scripts/avocado-flash` (`dispatch_boards` and its branch in `main`, which import `avocado_flash_boards.cli`) and the `boards` lines in its help text; otherwise `avocado-flash boards` imports a deleted package. If the board listing is still wanted, it must move instead of being deleted.
- [ ] `scripts/tests/boards`
- [ ] `scripts/tests/tegra`
- [ ] the `nvme` dispatch in `scripts/avocado-flash`: `dispatch_nvme` and its two `nvme` branches in `main`, plus the `nvme` lines in the help text
- [ ] the "Host tool tests" step in `.github/workflows/flash-tools-tests.yml`, and its path filter entries that only serve it (`scripts/**`; keep the `meta-avocado-nvidia/stone/**` entries, the engine tests still run)
- [ ] the host-door step in `docs/adding-a-flash-board.md` (the `scripts/avocado_flash_boards/tegra.py` registry entry and the host-door paragraphs)
- [ ] `scripts/tests/boards/golden/help.txt`, which lists `nvme`; it goes with `scripts/tests/boards`, and any remaining help golden must be regenerated without `nvme`

## 5. The gate

Do not remove the wrapper until both hold:

1. The hardware end-to-end run on the bench Orin Nano passes through `avocado provision`, covering:
   - an oversize image is refused before any erase
   - an empty or missing image is refused
   - a different Jetson in recovery is refused, naming both ids
   - a board with no recorded id is refused when unattended and warns on a terminal (3.5), and `AVOCADO_PROVISION_RCM_ID` supplies the id
   - a wrong retype aborts
   - `AVOCADO_PROVISION_FORCE=1` skips the confirmation
   - NVMe boot
   - SD boot
2. The avocado-cli change that exports `AVOCADO_PROVISION_FORCE` is settled. Without it, a run with no terminal flashes unconfirmed, and the engine cannot tell `--force` from a piped run. This is not met yet: avocado-cli 1.1.0 (`origin/main` at `2933188`) exports no such variable, and `--force` only sets `interactive: !force` (`src/commands/runtime/provision.rs`).

## 6. Out of scope

These stay in `scripts/avocado-flash`.

- `fuse-srk` (i.MX93): an irreversible fuse write, and there is no stone profile for it. It survives the wind-down.
- `ssh-emmc` (AGX Orin on the J5012 carrier): no stone profile. It survives the wind-down.

The i.MX93 `ums` flow is no longer here. `meta-avocado-nxp/stone/avocado-imx/stone-provision-ums.sh` is its stone profile (`ums` in `stone-imx93-frdm.json`), and the launcher drives the board's USB mass storage export around it (`scripts/avocado_flash_launch/ums.py`) so the operator does not type `ums` by hand. The nanopi-r5s also has a `stone-provision-ums.sh` (profile `sd-usb`) where the operator still types `ums` at the U-Boot prompt.

Winding down `fuse-srk` and `ssh-emmc` means writing new stone profiles or dropping them,
which is a separate design.

## 7. Ordering and rollback

Removal is a follow-up change. Nothing here deletes the wrapper, so until that
change lands both doors keep working and a regression in the engine can be
cross-checked against the wrapper. Settle the two open decisions in section 3 (3.2 and 3.4),
run the gate in section 5, then remove in one change so it reverts as one
commit.
