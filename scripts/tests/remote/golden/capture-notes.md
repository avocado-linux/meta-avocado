# Golden call logs (calls.log)

`calls.log` is the recording contract the parity suite compares against. It
holds the tool-call log the kit's own test fixtures record, one block per
case, from green runs of the kit's three test scripts.

## Source runs

The kit's tests were run from a copy of the kit under a scratch directory
(the originals and their evidence tree were not touched). Results of the
unmodified copies and of the capture-patched copies were identical:

| Script | Result | Exit |
|--------|--------|------|
| test-install.sh | tests: 97/97 | 0 |
| test-stage.sh | tests: 70/70 | 0 |
| test-window-scripts.sh | tests: 93/93 (all 5 mutants caught) | 0 |

The capture was run twice with the normalisation below and the two outputs
were byte-identical, so the file is deterministic.

## Format

Each case is:

```text
=== CASE <script>:<case-name>
exit=<n>
<recorded lines, possibly none>
```

- `install:` cases are the stub-tool log (`STUB_LOG`; line = tool basename
  followed by its argv, space separated) of each `install.sh` invocation.
- `window:` cases are the `STUB_LOG` of `preflight.sh` (`pf-*`) and
  `readback.sh` (`rb-*`), same line format.
- `stage:` cases are the stub-`ssh` record (`SSH_LOG`): a `CALL host=<h>` line
  and a `CMD <remote command>` line per connection. Cases that make no ssh
  call (dry-run, refused destination, missing source) have no lines.
- `exit=<n>` is the exit code of the script under test for that invocation.
- A case name seen more than once gets `#2`, `#3`, ... on later invocations
  of the same kit case (the kit runs `install.sh` several times inside one
  case, e.g. a real run, a re-run, and a `--restore`). Only the lines that
  invocation appended are recorded (a byte-offset delta of the log).

## Cases (87)

install (33 records): `install:dry`, `install:dry#2`, `install:ok` through
`install:ok#5`, `install:rmismatch1`, `install:rmismatch1#2`,
`install:rmismatch2`, `install:rmismatch2#2`, `install:rnostate`,
`install:disk-nvme0n1`, `install:disk-nvme0n1p1`, `install:disk-sda`,
`install:disk-nvme-dry`, `install:badsum`, `install:modified`,
`install:foreign`, `install:foreign-lsblk`, `install:mounted`,
`install:badcmd`, `install:unseated`, `install:readback`, `install:extracmd`,
`install:nearmiss`, `install:hdrv3`, `install:noarg`, `install:bochange`,
`install:noc`, `install:nocfb`, `install:devimages`, `install:nondevimages`.

stage (24): `stage:dry`, `stage:defsrc`, `stage:oldsrc`,
`stage:dev-_dev_shm_x`, `stage:dev-_dev_shm`, `stage:dev-_dev`,
`stage:dev-_dev_mmcblk0p1`, `stage:dev-_dev_.._run_x`, `stage:devmsg`,
`stage:out-_tmp_x`, `stage:out-_home_user_x`, `stage:out-_etc`,
`stage:out-_runx_y`, `stage:out-_run`, `stage:out-_var_tmp`,
`stage:out-_run_.._etc_x`, `stage:ok`, `stage:custom`, `stage:corrupt`,
`stage:corrupt-install.sh`, `stage:corrupt-preflight.sh`,
`stage:corrupt-readback.sh`, `stage:sshfail`, `stage:badsrc`.

window (30): `window:pf-good` (the good run), `window:pf-parttable`,
`pf-sectors`, `pf-readonly`, `pf-mounted`, `pf-bootnext`, `pf-bootorder`,
`pf-stale`, `pf-noC`, `pf-efivarfsro`, `pf-secureboot`, `pf-corrupt`,
`pf-space` (the 12 single-fault preflight runs), `pf-sb-absent`,
`pf-image-missing`, `pf-missing-tool`, `pf-no-manifest`, `pf-efi-fail`,
`pf-noroot`, `window:rb-default`, `rb-entry`, `rb-fallback`, `rb-differs`,
`rb-notmpfs`, `rb-mountfail`, `rb-missing-tool`, `rb-cleanup`,
`rb-cleanup-two`, `rb-cleanup-none`, `rb-cleanup-next-only` (each prefixed
`window:`).

`grep '^=== CASE ' calls.log` is the authoritative list. Good runs:
`install:ok`, `stage:ok`, `window:pf-good`, `window:rb-default`. Everything
else is a single-fault, refusal or alternate-mode case.

## Command used

Scratch tree: `$D=/var/tmp/claude-code/peridio/golden-capture`, holding copies
of `install.sh preflight.sh readback.sh stage.sh test-install.sh
test-stage.sh test-window-scripts.sh` in `$D/emmc/` and `factory.txt` in
`$D/inventory/`, plus `capture-lib.sh` (below).

```bash
: >"$D/raw.log"
export CAP_LIB=$D/capture-lib.sh CAP_OUT=$D/raw.log
for t in install stage window-scripts; do
  bash "$D/emmc/test-$t.sh" >"$D/cap-$t.out" 2>&1 </dev/null
done
cp "$D/raw.log" scripts/tests/remote/golden/calls.log
```

## What was changed in the copy

Only the three test scripts were patched; `install.sh`, `preflight.sh`,
`readback.sh` and `stage.sh` are byte-identical copies. The patch only adds a
hook that records each invocation; no assertion or fixture was altered.

1. Each test sources `$CAP_LIB` right after `set -uo pipefail` when set.
2. `test-install.sh`: `run_install` records the log size before the call and
   calls `cap_record "install:${CASE##*/}" ...` after it.
3. `test-stage.sh`: `run_stage`, `run_stage_default` and the two direct
   `bash "$UNDER"` invocations (`oldsrc`, `badsrc`) call `cap_record
   "stage:..." "$RC" "$SSH_LOG" ...` after the call. The two loops that named
   cases `dev$RANDOM` and `out$RANDOM` now name them from the destination
   (`dev-${d//\//_}`, `out-${d//\//_}`) because a random name cannot be a
   stable key. Nothing else in the loops changed.
4. `test-window-scripts.sh`: `run_pf` and `run_rb` call `cap_record
   "window:${C##*/}" ...` after the call.
5. `cap_record` (in `capture-lib.sh`) writes the header, `exit=`, and the
   normalised log delta to `$CAP_OUT`. It is a no-op when `TEST_NESTED=1`,
   or when `PREFLIGHT`/`READBACK` is set, so the kit's mutation-check
   subprocess runs (which re-run the suite against deliberately broken copies)
   are never recorded.

## Normalisation (apply identically in the parity suite)

Applied by `cap_record`, in this order, to every recorded line:

1. The case's own temp directory (`$CASE` for install and stage, `$C` for
   window) becomes `<TMP>`.
2. Any other scratch directory of the form
   `/var/tmp/claude-code/peridio/<name>.<6 alnum>` becomes `<SCRATCH>` (no
   occurrence remained in the final file).
3. The kit's default ssh alias (the real board's, which `stage.sh` defaults
   to) becomes `target-board`. Cases that pass `--host myboard` keep
   `myboard`.
4. `bhdr.<6 alnum>` (the mktemp name `install.sh` uses for its boot-header
   scratch file) becomes `bhdr.<RAND>`.
5. Every 64-hex-digit run (the sha256 sums in the stage verify command)
   becomes `<SHA256>`.

Timestamps: none appear in the recorded logs. Case order and `#N` suffixes
follow the order the kit runs them. Other fixed strings are left as the kit
emits them (for example the default destination `/run/emmc-test-images` and
the test file names such as `tegra234-test.dtb`).

## Scrub check

The final file and these notes were grepped case-insensitively for the
customer token and for the real ssh alias; neither occurs.
