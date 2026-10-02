# avocado_flash_remote: the ssh-emmc medium

`avocado-flash ssh-emmc` writes a board's internal eMMC from the board's own
running system, over SSH. It exists for boards whose eMMC cannot be reached
from the operator's machine (no USB download mode, no removable media) but
which boot a working system from somewhere else.

The tool has two halves:

- The host half (`cli.py`, `host.py`, `bundle.py`, `profile_resolve.py`) runs on
  the operator's machine. It resolves the board profile, copies the verified
  images and a runner bundle to the board, calls the runner over SSH, and
  collects and verifies the records the runner leaves behind.
- The runner half (everything else in this directory) is packed into one
  zipapp, `runner.pyz`, and runs on the board with the board's `python3`. It
  does every board operation.

Both halves use only the Python standard library, and the runner is written for
a board interpreter of Python 3.10 or newer. Nothing in a profile is ever
imported or executed; a profile only selects among a closed set of strategies.

## Invocation

`ssh-emmc` must be the first argument to `avocado-flash`. Everything after it is
parsed by `cli.py` and none of the local-medium options (`--machine`,
`--deploy`, `--backend`, ...) apply.

```text
avocado-flash ssh-emmc <subcommand> --board NAME --images DIR --host HOST [options]
```

`avocado-flash ssh-emmc --help` prints the same usage text this document is
written from.

### Options

| Option | Meaning |
|--------|---------|
| `--board NAME` | Board profile name. Required. |
| `--images DIR` | Image directory holding `MANIFEST.hashes`. Needed by `stage`. |
| `--host HOST` | `[user@]host`. Never starts with `-`. Required, except for `stage --dry-run`. |
| `--extension-dir DIR` | Board-support extension profile directory. |
| `--evidence-dir DIR` | Where per-run records are collected. Default `./ssh-emmc-evidence`. |
| `--dry-run` | `stage` only: list what would be copied, make no connection. |
| `--assume-yes` | Let the runner skip its own interactive prompt (see the retype gate below, which is separate). |
| `--ack-run RUN_ID` | Acknowledge a run (`write`, `restore`). |
| `--emergency-disarm` | `restore`: disarm without a run acknowledgement. |
| `--expected-boot-order V` | `check`, `write`: the comma-separated BootOrder the board must still have. |
| `--reference-boot-order V` | `readback`: the BootOrder recorded before the run. |
| `--run-id RUN_ID` | `write`, `restore`, `readback`, `status`: which run. |
| `--ssh-opt=OPT` | Extra ssh option, repeatable. Use the `=` form: `--ssh-opt=-p2222`. |
| `--batch` | Run ssh with `BatchMode=yes`. The default is `BatchMode=no`. |
| `--remote-python PATH` | Interpreter on the board. Default `python3`. |
| `--wait-seconds N` | `write`: how long to follow the run. Default 7200. |

### Exit codes

| Code | Meaning |
|------|---------|
| 0 | ok |
| 1 | refusal or failure |
| 2 | not examined (a check or readback could not look at its target), or the SSH connection dropped during `check`, `status`, `readback` or `restore` |
| 3 | profile mismatch (the bundled profile hash disagrees with the request) |
| 64 | usage error |
| 70 | unexpected error |
| 130 | interrupted |

Exit 2 is a separate answer from exit 1: a run that could not look has not
passed, and has not found a fault either. The same exit code is used when the
connection to the board dropped (ssh status 255) during `check`, `status`,
`readback` or `restore`: the runner may have acted before the drop, so run
`status` to see the recorded phase before doing anything else. A dropped
connection during `write` is not exit 2; the host reconciles with the board and
reports the recorded phase (see "Detached writes").

## Subcommands and their gates

A normal run is `stage`, `check`, `plan`, `write`, then (after the board
reboots into the test image) `readback`, and `restore` when you want to undo
the arming.

| Subcommand | What it does | Gate |
|------------|--------------|------|
| `stage` | Verifies the images against `MANIFEST.hashes`, builds `runner.pyz`, checks free space on the board, copies images, the exact profile and the bundle into the profile's staging directory, then re-verifies the hashes on the board. | Refuses when `MANIFEST.hashes` is missing, unparseable, names a missing file or disagrees with a file's sha256; when the staging filesystem lacks room (`staging.min_free_kib` plus the payload); and when the profile file changed after it was resolved. `--dry-run` lists files and sizes and makes no connection. |
| `check` | Read-only preflight. Runs every assertion in the profile's `checks` list and prints one `PASS` or `FAIL` line each. | Exit 0 only when every check passed and every listed check was examined (`checks: N/M` with N equal to M). Exit 1 when any check failed. Exit 2 when nothing failed but a check could not run. |
| `plan` | Looks, decides, and writes one plan record (`plan.json`). Changes nothing on the board. Creates the run id. | Refuses on a wrong device name, wrong sector count, a target that backs the running system or is mounted, a non-empty target when `require_empty` is set, a layout that does not fit, staged images that fail their checksums, a failing guard, or an arm pre-flight refusal. |
| `write` | Writes the planned run: partition table, then each image, read-back verification, guard, arm. Runs detached on the board (see `--detach`). | See the write gates below. |
| `readback` | After the test image has booted, mounts the profile's data partition read-only, copies the persistent journal and boot logs, compares BootOrder with the reference, and prints (never runs) cleanup commands. | Needs `--reference-boot-order` unless the profile's arm strategy is `none`. Refuses to mount when the output directory is not on tmpfs, so logs never land on the live system's disk. |
| `restore` | Undoes the arming. See "Restore scope". | Takes the per-host lock and, on the board, the on-board flash lock: it refuses while another holder (a write in progress) is live. A run in a non-terminal phase needs `--ack-run RUN_ID` naming it. `--emergency-disarm` needs `--ack-run`. |
| `status` | Prints the board's recorded phase: `status: PHASE run=RUN_ID recovery=TEXT`, or `status: no run recorded`. Strictly read-only. | None. Use it after a dropped connection. |

### Write gates

All of these hold before the first byte is written to the board:

1. A collected plan record for `--run-id` exists under the evidence directory
   and its record set verifies (`MANIFEST.json` hashes match). Otherwise the host
   refuses with "run plan first".
2. The host prints the target device and every image-to-partition mapping, then
   asks you to retype the device (for example `/dev/mmcblk0`). Any mismatch
   refuses, and nothing is written. This gate is separate from `--assume-yes`,
   which only affects the runner's own prompt.
3. The host takes the per-host lock (`.lock-<host>` in the evidence directory)
   and refuses while another run holds it.
4. On the board, the runner re-checks that the staged image hashes, the profile
   hash, the board identity (machine id and device serial), the target device
   and the partition table input all still match the plan record.
5. The guard's staged-image check passes.
6. No unfinished earlier run is recorded in the state directory (see the
   recovery table), and the plan was not already used by a finished run.
7. The on-board flash lock is held.
8. The preflight check passes again, and the plan's device, sector count,
   in-use and emptiness tests pass again.
9. The runner's own confirmation matches the device, unless `--assume-yes` was
   given.

A write is reported `COMPLETE` only when the board's last recorded phase is
`complete` and the collected records verify. A board that says `complete` but
whose records do not verify is reported as not verified, with exit 1.

## Board profiles

A profile is a JSON file named `<board>.json`. Two ship with the tool, in
`profiles/`:

- `jetson-agx-orin-j5012.json`: a real board. Writes the internal eMMC from the
  running NVMe system, arms a one-shot UEFI boot entry and guards against
  booting a kernel that would see the NVMe disk.
- `fixture-none.json`: a stub device for the generic lifecycle tests. It arms
  nothing and guards nothing. Its `checks` list names `device-exists` and
  `device-empty`, which have no implementation in `cmd_check.py`, so running
  `check` against it with the real runner reports those checks as not examined
  (exit 2). It is meant to be used with the stub transport, not a real board.

### Resolution and override order

The profile for `--board NAME` is looked up in this order, and the first file
found wins:

1. The directory given with `--extension-dir`, if any. This is how a
   board-support layer supplies or overrides a profile; the code has no other
   lookup, so a BSP extension directory is used only when it is passed here.
2. The tool-shipped `profiles/` directory.

Rules that follow from `profile_resolve.py`:

- The board name must be kebab-case `[a-z0-9-]+` with no leading dash.
- An invalid profile in the extension directory is an error. It never falls back
  silently to the shipped one.
- When both directories hold a file of that name, the output line says
  `shadows shipped: <path>`.
- A candidate that is a dangling symlink, or resolves outside its own
  directory, is refused.
- The file's `board` field must equal the requested name.
- The file is read once as bytes. Those exact bytes are validated, hashed
  (sha256), bundled and sent to the board, so host and runner agree on the
  hash. The host rechecks before bundling that the file is unchanged, and the
  runner exits 3 if the bundled profile, `BUNDLE.json` and the request disagree.

An unknown board lists the known board names.

### Schema version 1

Every object is closed: an unknown key anywhere is an error naming its dotted
path. Numbers must be plain integers. Duplicate JSON keys are rejected.

| Field | Contents |
|-------|----------|
| `schema_version` | Must be `1`. |
| `board` | Kebab-case name, `[a-z0-9-]+`. |
| `description` | Optional string. |
| `target` | `device`, `sector_size`, `sectors`, `require_empty` (bool), and `identity`. |
| `target.identity` | `kind` (one of `by-path`, `serial`, `sysfs-name`), `value`, optional `sysfs_attr`. |
| `layout` | `{"strategy": "explicit-table", "params": {...}}`. |
| `images` | Map of role name to `{partition, max_bytes, must_be_populated, file}`. `file` is a plain file name: no separators, no leading dash. |
| `checks` | List of unique preflight assertion names. |
| `arm` | `{"strategy": "uefi-bootnext" or "none", "params": {...}}`. |
| `guard` | `{"strategy": "boot-arg" or "none", "params": {...}}`. |
| `staging` | `dir` (absolute) and `min_free_kib`. |
| `state_dir` | Absolute directory for run state on the board. |

`staging.dir` and `state_dir` must be absolute, must not contain `..`, and must
not be under `/dev`, `/sys` or `/proc`.

Cross-checks applied when the layout is `explicit-table`: `target.sectors` and
`target.sector_size` must equal the layout's `device_sectors` and `sector_size`;
every image's `partition` must be a number in the layout table; and every
partition named by a `boot-arg` guard must exist in the table by name.

The preflight check names the runner implements are `emmc-exists`,
`target-identity`, `emmc-not-read-only`, `emmc-sector-count`,
`emmc-no-partition-table`, `emmc-not-mounted`, `efibootmgr-supports-create`,
`boot-order-unchanged`, `boot-next-unset`, `no-stale-oneshot-entry`,
`efivarfs-rw`, `secure-boot-disabled`, `staged-images-present`,
`staged-image-checksums` and `staging-space-free`. `boot-order-unchanged` is not
examined unless `--expected-boot-order` is given.

### Pinning the eMMC serial in an extension profile

A shipped profile cannot know your board's eMMC serial, so it identifies the
target by device name and sector count only, and that name check can never
differ. Pin the serial in a profile you supply through `--extension-dir`:

1. Copy the shipped profile for your board into the extension directory under
   the same file name (`<board>.json`); it then shadows the shipped one.
2. Set `target.identity` to `{"kind": "serial", "value": "<serial>", "sysfs_attr": "serial"}`.
   The runner reads `/sys/block/<device>/device/<sysfs_attr>` and compares it
   with `value`. Read your own board's value with
   `cat /sys/block/mmcblk0/device/serial` on the board. The examples here use
   the synthetic value `0x0badc0de`; never commit a real serial.
3. Add `target-identity` to the profile's `checks` list. The shipped profile does
   not list it, so without this `check` never examines identity at all and
   cannot report a wrong board. `plan` verifies a pinned serial on its own, but
   `check` only runs what `checks` names.

```json
"target": {
  "identity": {"kind": "serial", "value": "0x0badc0de", "sysfs_attr": "serial"}
},
"checks": ["emmc-exists", "target-identity"]
```

(The `checks` list shown is abbreviated; keep the shipped entries and add
`target-identity` to them.) Then run `check --extension-dir DIR`: it prints a
`PASS` line for `target-identity` only when the serial matches.

### Adding a board

Adding a board is a profile-only change. There is no code to write and none to
load. Strategies are a closed registry in `strategies.py`; a profile chooses
among them and supplies declarative parameters.

| Kind | Allowed strategies | Parameters |
|------|--------------------|------------|
| `arm` | `uefi-bootnext` | `label`, `loader_path`, optional `boot_args` (all strings). Creates one entry with `efibootmgr -C` and sets `BootNext` only. Never writes the boot order. |
| `arm` | `none` | None. Nothing is armed. |
| `guard` | `boot-arg` | `argument` (string) and `partitions` (list of layout partition names). Reads the boot image header and refuses to arm unless the argument is in its command line. |
| `guard` | `none` | None. |
| `layout` | `explicit-table` | `sector_size` (default 512), `first_lba`, `last_lba`, `device_sectors`, and `table`. |

An unknown strategy name, an unknown parameter or a missing required parameter
is a profile error. A new strategy is a code change to `strategies.py` and the
modules that implement it, not a profile change.

Layout rules enforced by `explicit-table`: `last_lba` must equal
`device_sectors - 34` (the GPT secondary table); `first_lba` must not be after
`last_lba`; the table must not be empty; each partition has a positive,
unique `number`, a unique non-empty `name`, a `start`, a positive `size`, a
`type_guid` (and optional `uuid`) in 8-4-4-4-12 hex form; every partition must
sit within `first_lba` and `last_lba`; and no two partitions may overlap.

To add a board:

1. Copy the closest shipped profile to `<board>.json`.
2. Set `board` to the same name as the file.
3. Fill in `target`, the full partition `table`, `images`, `checks`, the `arm`
   and `guard` strategies, `staging` and `state_dir`.
4. Put it in a directory and pass that directory with `--extension-dir`, or add
   it to `profiles/` if it ships with the tool.
5. Run `avocado-flash ssh-emmc stage --dry-run --board <board> --images DIR`.
   This validates the profile (the error names the dotted path of the first
   fault) and lists what would be copied, without a connection.

## Run state and recovery

The runner keeps one JSON document per run at
`<state_dir>/<run_id>/state.json`, and `<state_dir>/current` names the active
run. Every write is temp file, fsync, rename, directory fsync, so an interruption
leaves either the previous complete file or the new complete file. Decisions use
the phase and a monotonic sequence number, never wall time.

Phases, in order: `planned`, `table-writing`, `table-written`, `image-writing`,
`image-written`, `verified`, `arming`, `armed`, `complete`. `failed` can follow
any non-terminal phase. `restored` is written by a successful `restore` and can
follow any phase. `complete`, `failed` and `restored` are terminal.
`image-writing` and `image-written` repeat once per image, in the profile's
image order. `arming` and `armed` are skipped when the profile's arm strategy
is `none`. `arming` is recorded before the first boot-entry change, so a run
that dies or fails inside the arm step is left in `arming`, not in `verified`.

A run that ends normally is in a terminal phase. A non-terminal phase on the
board means the runner was killed or lost power mid-run. While one is recorded,
a new `write` is refused with a message beginning "a previous run is not
finished" and naming the permitted recovery. A run acknowledged with `--ack-run`
is allowed through for recovery only: `write` still refuses and tells you to run
`restore`, wipe the target by hand if it has a table, stage the images again, then
`plan` and `write`.

Find the phase with `avocado-flash ssh-emmc status --board NAME --host HOST`.

The recovery actions are `none-recorded`, `restore-then-restart`, `restore` and
`restore-unknown-arm`; `status` prints the action followed by its full text.

| Phase on the board | What it means | Operator action |
|--------------------|---------------|-----------------|
| `planned` | The state file was created and no board change is recorded. The run never reached the first mutation. | None recorded (`none-recorded`). Safe to discard only if the run never took the on-board lock; check the lock before rerunning after acknowledging the run. |
| `table-writing` | Killed during the partition table write. The table may be partly or fully rewritten. | `restore-then-restart`: re-inspect the target, run `restore --ack-run RUN_ID` (disarms and cleans staging; it does not roll back the table and wipes nothing), then follow [Starting over after a failed write](#starting-over-after-a-failed-write): wipe the table by hand, stage again, plan and write. |
| `table-written` | The table is written; no image has started. | `restore-then-restart`, as above. |
| `image-writing` | Killed while an image was being written. That partition holds partial data. | `restore-then-restart`, as above. |
| `image-written` | At least one image is written and verified by read-back; more remain. | `restore-then-restart`, as above. |
| `verified` | All images are written and read back correctly, but the guard or arming did not finish. | `restore --ack-run RUN_ID`. Do not rewrite the images. |
| `arming` | The arm step started and did not finish (the runner was killed, or the arm step failed and was handled). A boot entry and `BootNext` may already exist even though the record does not name them. | `restore-unknown-arm`: DO NOT REBOOT. Run `restore --ack-run RUN_ID`; it finds the entry by its label when the number was never recorded. |
| `armed` | The boot entry exists and `BootNext` may be set. The board will boot the test image on the next reboot. | `restore --ack-run RUN_ID`. Do not reboot first unless you want to boot the test image. |
| `complete` | Terminal. | No recovery needed. |
| `failed` | Terminal. | The recovery text names what is left: whether the table was possibly rewritten, which images are written, partial or not started, and whether a boot entry was armed ("DO NOT REBOOT" until `restore` removes it). Run `restore` (no acknowledgement needed for a finished run). If the table was possibly rewritten, follow [Starting over after a failed write](#starting-over-after-a-failed-write) before planning again; otherwise stage the images again, then plan and write. |
| `restored` | Terminal. Written by a successful `restore`. | No recovery needed. The state gate accepts a new plan and write, but `plan` still refuses a target that has a partition table when the profile sets `require_empty`. |
| state unreadable | The state file or `current` pointer is missing or malformed. | Manual: inspect the state directory and the board's `efibootmgr -v`, then use `restore --emergency-disarm`. |

The recovery column is the text `status` and the write refusal print. It is
advice about what state the target may be in; what `restore` actually changes is
listed next.

## Starting over after a failed write

`restore` closes the run, disarms the boot entry and deletes the staging
directory. It does not touch the partition table, and the shipped profiles set
`require_empty`, so `plan` refuses a disk that already carries a table. After a
run that reached `table-writing` (the phases `table-writing`, `table-written`,
`image-writing`, `image-written`, or a `failed` run whose recovery text says the
table was possibly rewritten) a fresh attempt therefore needs these steps, in
this order:

1. Run `restore --ack-run RUN_ID` and read what it printed. Do not reboot while
   a boot entry is armed.
2. Re-check the device identity yourself, on the board: the device name, its
   size and its serial must match the profile's `target` and `identity`
   (`lsblk -o NAME,SIZE,SERIAL,MOUNTPOINTS DEVICE`). If they do not, stop: this
   is not the disk the profile names.
3. Wipe the partition table of that device by hand, for example
   `wipefs --all DEVICE` as root, then confirm `lsblk DEVICE` shows no
   partitions.
4. Run `stage` again: `restore` deleted the staging directory, and the images
   must be copied and hash-checked afresh.
5. Run `plan`, then `write`.

The tool does not do step 3 for you. A wipe inside `restore` would give a command
that is meant to disarm and clean up the reach to erase a disk, so it stays a
manual step with the identity check in front of it.

A run that failed before `table-writing` never touched the table: skip steps 2
and 3.

## Restore scope

`restore` is a disarm and a clean-up. It is not a rollback.

What it does, per `cmd_restore.py`:

- Removes the boot entry this tool created, matched by both its recorded entry
  number and its label, and clears `BootNext`.
- Checks that `BootOrder` still equals the value recorded before any mutation,
  and reports a difference without changing it.
- Removes the profile's staging directory, only when the path is exactly the
  profile's `staging.dir`, is deep enough, and is not a symlink.
- If the board already booted the test entry (`BootCurrent` equals the recorded
  entry), leaves the boot entries alone and cleans staging only.
- If no entry was armed, makes no `efibootmgr` calls and cleans staging only.
- If the state file is unreadable, refuses and touches nothing.
- When the arm step started but no entry number was recorded, finds the entry by
  its label. It deletes nothing if any labelled entry is in `BootOrder` or is
  `BootCurrent` (the board booted it): it names the entry and leaves the decision
  to you, with `efibootmgr -v` as the place to look.

What it does not do: it does not restore the partition table and it does not
restore any image content. Its output says so
(`note: restore does not roll back partition table or image changes`). It does
not touch `state.json` until it has succeeded; then it advances the run to the
terminal `restored` phase so that a new plan and write are accepted. A failed
restore leaves the phase as it was.

Before doing anything `restore` takes the on-board flash lock and refuses at once
while another holder is live, so it cannot delete staging under a running write. A
run still in a non-terminal phase is restored only with `--ack-run RUN_ID`
naming that run.

`restore --emergency-disarm --ack-run TEXT` is for a missing or unreadable state
file. It requires a non-empty acknowledgement and removes only boot entries whose
label equals the profile's `arm.params.label`, plus `BootNext` if it points at
one of them. `BootOrder`, all other entries and staging are left alone. Like the
label-based path above, it deletes nothing when a labelled entry is in `BootOrder`
or is `BootCurrent`.

`--emergency-disarm` does not depend on the run state, so a hung write that still
holds the flash lock must not block it for good. It waits up to 15 seconds for the
lock. If the lock stays held it exits 1 having touched nothing, prints the holder
(the pid and run id from the lock file) and the manual commands:
`efibootmgr -v`, `efibootmgr -N`, and `efibootmgr -B -b XXXX` for one labelled
entry that is not in `BootOrder` and is not `BootCurrent`. The normal `restore`
keeps refusing at once while the lock is held.

## Privilege and sudo

The runner needs root. After connecting, the host decides how to get it:

1. If the login uid on the board is 0 (`id -u`), privileged commands run
   directly with no sudo and no prompt. The tool prints `privilege: root (no sudo)`.
2. Otherwise it tries `sudo -n true`. If that works it prints
   `privilege: sudo (password not needed)`.
3. Otherwise it asks for the password on the operator's terminal
   (`getpass`) and verifies it with a trivial privileged command. It prints
   `privilege: sudo (password supplied)`. With no terminal to ask on, it
   refuses instead of hanging.

The password is only ever the first line of standard input to `sudo -S -p ''`
on each privileged ssh call. It is never put in an argument list, the
environment, a log, an exception message, a record or a `repr()`. A streamed
payload cannot be combined with a password and is refused. An `id -u` answer
that is not a plain decimal is a refusal, not a guess; a failed or empty answer
is treated as not root and takes the sudo path.

ssh itself runs with `BatchMode=no` by default so you can type an ssh password
through your own agent. Pass `--batch` for key-only setups where a prompt must
fail instead of waiting.

## The remote interpreter

The runner needs a `python3` on the board with the standard-library modules it
imports. `--remote-python PATH` names a different interpreter. The value is
spliced into a remote command line, so it must be an absolute path or a plain
command name made of `[A-Za-z0-9_./+-]`, must not start with `-`, and must not
contain a `..` segment.

Before any runner call (and so before `stage` copies anything), the host runs a
probe with that interpreter that tries to import every standard-library module
the runner bundle needs. It prints the interpreter version on success
(`remote python: python3 3.x.y`) and refuses with a message that names the
cause otherwise:

- the interpreter was not found (exit status 127 from the board);
- the interpreter failed to run;
- the interpreter lacks named standard-library modules, which is typical of a
  stripped-down board python.

Each refusal tells you to install a full `python3` or pass `--remote-python`.
After copying the bundle, `stage` also confirms that the board's interpreter can
open the staged archive.

## Detached writes

`write` is run detached on the board so that a dropped SSH connection does not
kill a half-written disk. This is the runner's `--detach` option (valid for
`write` only), and the host adds it automatically; it is not an option of
`avocado-flash ssh-emmc` itself.

The runner double-forks, starts a new session, redirects its output to
`<run_dir>/runner.log` on the board, and returns immediately with
`detached: run=<id> log=<path>`. The host then polls the board's `status` every
few seconds until the run reaches a terminal phase or `--wait-seconds` elapses.
A connection error during polling is reported and retried. If the board records
no state for the run after three polls, the host reports that the write did not
start and prints the tail of `runner.log`. If `--wait-seconds` runs out the
write keeps going on the board; follow it with `status`. Ctrl-C on the host has
the same effect: a started write is not stopped.

A write whose run id already has a state record (or whose run directory holds
`write.json`) is refused by the runner before it detaches: the host gets exit 1
and the refusal on stderr, never follows it, and the finished records are left as
they were.

Each `write` invocation sends a fresh random nonce (`invocation_nonce`). Before
it touches any marker the detached runner takes a per-run lock
(`<state_dir>/.invocation-<run_id>.lock`) that the detached process holds for as
long as it lives, so a second invocation of the same run id while the first is
still working (even while it is only hashing and has no state record yet) is
refused with exit 1 and "already in progress". That refusal changes nothing: the
running runner's markers, verdict and manifest are left alone, no `outcome` is
written for the run, and the refusal text never says the board is unchanged,
because it is not. A crashed runner releases the lock with its process.

When the host stops following a run: at the start of every invocation the runner
deletes the previous `accepted` and `outcome` markers, then a detached runner
writes its pid and the invocation's nonce to an `accepted` marker file in the run
directory before it does any check or hashing, and, when it ends, an `outcome`
marker (also carrying the run id and the nonce): `finished`, or
`refused` followed by the board's own refusal text for a write turned away before
the lock (an unfinished prior run, a failed check, a changed `BootOrder`, a
confirmation mismatch). A runner that crashed writes no `outcome`. The host reads
`outcome` first and prints a `refused` text verbatim with exit 1. Anything the
host cannot read (a dropped ssh, a sudo failure, an unrecognised answer, an
`outcome` written for another run or another invocation) is unknown, and an unknown never ends the
follow or produces a "did not start" or "exited" verdict; the host keeps waiting
until `--wait-seconds` runs out. When a run reaches `complete`, the host also
checks that the run's `accepted` marker carries this invocation's nonce and that no
refusal is recorded for it, and does not print `COMPLETE` otherwise (a replay that
was turned away, followed after a dropped connection, lands here: the host reports
the run's phase and says this invocation did not write it) or if the board could not
confirm it. The marker probes decide absence by their own exit code, never by the
wording of a localised error message. Before declaring
a runner dead the host reconciles once more, so a run that finished between the
poll and the probe is reported as complete. If the recorded phase is non-terminal and has not moved between two
polls, the host looks at that pid. A runner that is gone cannot advance the
phase, so the host stops at once instead of polling until `--wait-seconds`,
prints the recorded phase and its recovery text (for `arming`: the arm state is
unknown, DO NOT REBOOT, run `restore --ack-run RUN_ID`), and exits 1. A runner
that is still alive in a non-terminal phase keeps being followed. The `accepted`
marker is also what separates "slow" from "never started" when the board
records no state at all: marker present with a live or unreadable pid means keep
waiting, marker present with a dead pid means the runner exited without
recording state, no marker and no state means the write did not start.

## Evidence records

Each run has a directory under `--evidence-dir` on the operator's machine, named
`run-<UTC timestamp>-<8 hex>`; that name is the run id. On the board the same
records are written under `<state_dir>/<run_id>/records`.

| Record | Written by |
|--------|------------|
| `plan.json` | `plan`: run id, profile hash, board identity, device, image hashes and sizes, partition table hash, arm summary, creation time. |
| `write.json` | `write`: final phase, error, per-image state, arm record, transition log. |
| `runner.log` | A detached `write`: the runner's output. |
| `accepted` | A detached `write`: the runner's pid and the invocation nonce, written before any check. Rewritten on every invocation. |
| `outcome` | A detached `write` that ended: `finished`, or `refused` with the board's refusal text, after the run id and nonce lines. Listed in `MANIFEST.json` like the other files; absent when the runner crashed. |
| `MANIFEST.json` | Written last by the runner for each run directory. Lists every record with size and sha256, plus host tool version, runner version, profile hash, image hashes, board identity, transition log, clocks (including skew) and `run_status` (`runner-complete` when the subcommand exited 0, otherwise `incomplete`). |

The host collects the on-board records after `plan` and after `write`, into
`<evidence-dir>/<run-id>` and `<evidence-dir>/<run-id>-write`, and verifies the
set: every file listed in `MANIFEST.json` must exist with the recorded size and
hash, and no unlisted file may be present. The record stream is rejected if it
contains anything but flat regular files. Timestamps and clock skew are
evidence only; nothing is authorised on a clock.

A record set that fails verification is reported with the first problems found
and exit 1, whatever the board claimed.

## Opt-in loop-device rehearsal

A rehearsal that runs the real, non-stub runner as root against a loop-backed
block device is planned (change task 7.3, with a fixture profile) but is not yet
provided: `tests/remote/test_rehearsal_loop.py` does not exist in this tree. Until
it does, the default suite (`tests/remote`) runs only against the stub
transport and in-process fakes, with no ssh and no network, and the end-to-end
behaviour on a real board has to be exercised by hand with `check`, `plan` and
`write` against a spare board.

## Tests and hygiene gate

```text
cd scripts
uv run --with pytest python3 -m pytest tests/remote -q
uv run --with pytest python3 -m pytest tests/remote/test_hygiene.py -q
```

The hygiene gate fails on a leaked test password in a record, log or source
file, on a forbidden token anywhere in this tree (including this file), on a
runner-side module importing outside the standard library, and on a plan,
check or status module that can reach a mutating verb.
