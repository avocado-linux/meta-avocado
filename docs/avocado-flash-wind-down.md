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
- `device-confirmation`: `confirm.py` asks the operator to retype the target before writing, and the prompt names every medium the erase flags destroy, including QSPI and UEFI variables; `AVOCADO_PROVISION_FORCE=1` skips it.
- upstream-drift record: `meta-avocado-nvidia/stone/tegra/upstream-tracking.json`, checked by `meta-avocado-nvidia/stone/tegra/tests/test_upstream_drift.py`.

## 3. Wrapper-only today: these BLOCK removal

Six guards live only in the wrapper: the three in 3.1 to 3.3, the unpinned
confirmed board in 3.4, and the two below in 3.5 and 3.6. Each needs a
decision before removal. The options are listed; this document does not pick
one.

### 3.1 PATH hardening

Today: `scripts/avocado_flash_tegra/plan.py`, `safe_path()`, keeps only the
absolute components of the caller's `PATH` (falling back to a system path)
before running the script as root. An empty or relative component means the
current directory, which is the deploy directory, so root could resolve `jq`,
`cpp` or `fdtget` from a place the caller does not control.

Decision, one of:

- Move into the engine: sanitize `PATH` in the engine's toolchain/runner setup.
- Move to avocado-cli: `avocado provision` sets a clean `PATH` when it launches the script as root.
- Drop: accept that root runs with the caller's `PATH`.

### 3.2 Per-run log file

Today: `scripts/avocado_flash_tegra/runner.py`, `stream()`, tees the script's
output to a log file for each run, so a failed flash leaves a record.

Decision, one of:

- Move into the engine: the engine's `runner.py` writes a per-run log.
- Move to avocado-cli: `avocado provision` captures and keeps the output.
- Drop: rely on the terminal scrollback.

### 3.3 Refusing a run with no pinned kernel

Today: the wrapper requires the kernel `Image` in the deploy tree and refuses
without it. Via `avocado provision`, the engine only warns and takes the
prebuilt `boot.img` when `avocado install` pinned no kernel, so a board can be
flashed with a kernel nobody chose.

Decision, one of:

- Move into the engine: refuse instead of warn when no kernel is pinned.
- Move to avocado-cli: `avocado provision` refuses before invoking the script when `avocado install` pinned no kernel.
- Drop: keep the warning and the prebuilt-image fallback as the intended behavior.

### 3.4 The confirmed board is not pinned to the flash

Today the wrapper has an operator retype the board's `bus:device`, then runs
the engine with `AVOCADO_PROVISION_FORCE=1` and passes it no device identity.
The engine stages for minutes, waits for a recovery device, and checks that one
board is still there before the flash. That check compares only against the
engine's own wait, so a board of the same model swapped in during staging is
flashed without the operator confirming it. `./initrd-flash` is also run with
only the erase flags, so the tool chooses its device itself and the engine's
choice is advisory. Under `avocado provision` the engine prompts after its
wait, so staging is not exposed there; only the gap between the recheck and the
tool's own enumeration remains.

Decision, one of:

- Move into the engine: accept the confirmed `bus:device` in a new variable, refuse in the wait and the recheck unless it matches, and pass the device to `initrd-flash` if the tool takes an instance argument.
- Move to avocado-cli: `avocado provision` confirms and passes the identity through.
- Drop: accept that a swap during staging is the operator's responsibility.

### 3.5 Refusing a machine with no recorded recovery id

Today: `scripts/avocado_flash_tegra/rcm.py`, `expected_rcm_id()`, raises
`FlashError` when the machine has no registry entry or no recorded
recovery-mode USB id, and tells the operator to pass `--rcm-id`. The engine
does not refuse: `avocado_tegraflash/recovery.py`, `wait_for_single_board()`,
only logs "the board is not identity-checked" and proceeds with the one device
in recovery when `expected_ids` is empty. Six of the seven stone manifests
declare no `rcm_ids`, so for those machines the engine has no identity check
at all.

Removing the wrapper therefore drops a refusal. With
`AVOCADO_PROVISION_FORCE=1`, or a run with no terminal, the engine skips the
confirmation too, so a flash for a module with no declared id proceeds
unconfirmed against whichever lone NVIDIA device is in recovery, for example
an Orin Nano. Whether `initrd-flash` would then erase that board or fail when
it boots the wrong RCM payload is unproven; do not rely on it failing.

Decision, one of:

- Move into the engine: refuse when no ids are declared and `AVOCADO_PROVISION_FORCE=1` (or a non-tty run) would skip the confirmation.
- Move into the engine: declare `rcm_ids` for every manifest, so the warning branch is unreachable.
- Drop: accept the warning as the only protection.

### 3.6 Work directory ownership and mode refusals

Today: `scripts/avocado_flash_tegra/workdir.py` refuses, because the helper
staged there runs as root:

- `require_private_dir` (line 62): a work directory that is not a real directory (a symlink or other file), is not owned by the current user, or is writable by group or others.
- `require_safe_ancestors` (line 81): any existing ancestor, symlinks resolved, that is not owned by root or the current user, or is writable by group or others without the sticky bit.
- `create_workdir` (line 110): a default (tool-chosen) work directory that already exists, and an explicit one that fails `require_private_dir`.

The engine has no equivalent of these checks, so another user who can pre-create
or write the directory could choose what root executes.

Decision, one of:

- Move into the engine: apply the same checks to the engine's work directory before staging.
- Move to avocado-cli: `avocado provision` creates the work directory privately and passes it in.
- Drop: accept that the work directory is trusted.

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
   - a board with no recorded id warns and proceeds (this changes if 3.5 moves the refusal into the engine)
   - a wrong retype aborts
   - `AVOCADO_PROVISION_FORCE=1` skips the confirmation
   - NVMe boot
   - SD boot
2. The avocado-cli change that exports `AVOCADO_PROVISION_FORCE` is settled. Without it, a run with no terminal flashes unconfirmed, and the engine cannot tell `--force` from a piped run.

## 6. Out of scope

These stay in `scripts/avocado-flash`.

- `fuse-srk` (i.MX93): an irreversible fuse write, and there is no stone profile for it.
- `ssh-emmc` (AGX Orin on the J5012 carrier): no stone profile.
- automated `ums`: no stone profile.

Winding any of them down means writing new stone profiles or dropping them,
which is a separate design.

## 7. Ordering and rollback

Removal is a follow-up change. Nothing here deletes the wrapper, so until that
change lands both doors keep working and a regression in the engine can be
cross-checked against the wrapper. Settle the six decisions in section 3,
run the gate in section 5, then remove in one change so it reverts as one
commit.
