# Adding a Flash Board

This guide is for an engineer adding a Jetson board that `avocado-flash nvme`
and `avocado provision` can write. It covers the three things a board needs,
how to check them without hardware, and what changed for existing users when
the provisioning script became a thin shim over one engine.

## What a flash board is

A flash board is three pieces that have to agree:

- A stone manifest under `meta-avocado-nvidia/stone/` that names
  `stone-provision-tegraflash.sh` in its profiles.
- An engine entry in that manifest, so stone copies the provisioning engine
  next to the script.
- The recovery id and its evidence in the same manifest
  (`tegraflash.rcm_ids` and `tegraflash.rcm_evidence`). No Python board table is
  involved: the engine and the launcher's `boards` verb read the manifest. The
  old registry in `scripts/avocado_flash_boards/` still exists but is retired by
  this change's default flip of the launcher (`AVOCADO_FLASH_LAUNCHER`); do not
  add a board to it.

Two doors write a board, and both run the same file. The host door,
`avocado-flash nvme`, runs `stone-provision-tegraflash.sh` from the deploy
tree. `avocado provision` runs it from the stone output directory. That file
is a shim: it starts the Python engine in
`meta-avocado-nvidia/stone/tegra/avocado_tegraflash/` with `python3 -I -B`,
so the two doors cannot drift apart.

## 1. The stone manifest

Create `meta-avocado-nvidia/stone/stone-<name>.json`, where `<name>` is the
machine name without its `avocado-` prefix (`stone-jetson-orin-nano.json` is
for `avocado-jetson-orin-nano`). Copy the closest existing Jetson manifest;
the manifest must name `stone-provision-tegraflash.sh` in its profiles.

The five profile names the engine accepts, from
`avocado_tegraflash/profile.py`:

| Profile | Boot media |
|---------|------------|
| `tegraflash` | NVMe |
| `tegraflash-nvme` | NVMe |
| `tegraflash-mmc` | eMMC |
| `tegraflash-emmc` | eMMC |
| `tegraflash-sd` | SD |

Any other name is refused (see Breaking changes).

The engine reads these keys from `storage_devices.rootdisk` (the list is
`KEYS` in `avocado_tegraflash/manifest.py`):

| Key | Meaning |
|-----|---------|
| `images.rootfs` | Root filesystem image |
| `images.var` | `/var` image |
| `images.initramfs` | The runtime initramfs |
| `images.tegraflash_initramfs` | Initramfs that runs on the board during the flash |
| `images.tegraflash_esp` | EFI system partition image |
| `images.tegraflash_tos` | Trusted OS image |
| `images.tegraflash_bsp` | The BSP directory the flash is staged from |
| `images.tegraflash_tools` | Host tools directory |
| `images.tegraflash_carrier_bsp` | Slot for a carrier extension's overlay |
| `images.dtb` | DTB override; optional, the BSP's own DTB is used without it |
| `images.bpmp_dtb` | BPMP DTB override; optional, same fallback |
| `tegraflash.overlays` | Overlay list; optional, absence means none |
| `tegraflash.dce_overlays` | DCE overlay list; optional |
| `tegraflash.sd_device` | SD device name for the SD profile |
| `tegraflash.rcm_ids` | List of lowercase `vendor:product` USB ids this board may show in recovery mode; the engine refuses a recovery device whose id is not listed. It narrows the match only: a device still has to be recognised as a recovery device first (see below). Optional, but without it the engine refuses an unattended run and only warns when an operator retypes the confirmation (see `AVOCADO_PROVISION_RCM_ID`) |
| `tegraflash.rcm_evidence` | Object mapping each declared id to what was seen on hardware, for example the `lsusb` line. Required for every id in `rcm_ids`, and an entry for an undeclared id is an error |

Add the recovery ids you observed on hardware to `tegraflash.rcm_ids` in the
manifest, and the evidence beside them, for example:

```json
"rcm_ids": ["0955:7523"],
"rcm_evidence": {
  "0955:7523": "lsusb on the bench Orin Nano showed 0955:7523 NVIDIA Corp. APX"
}
```

List another SKU's id only after that module has been seen in recovery mode.
Leave both out until someone has seen the board in recovery mode; guessing an id
would pin a different device. The launcher's `boards` verb
(`python3 scripts/avocado-flash boards`) validates the shape: a lowercase
`0955:xxxx` pair, non-empty evidence, no evidence for an undeclared id.

The list does not teach the engine a new id. The engine counts a device as a
recovery device when its description says APX or RCM, or its product id is in
`RECOVERY_PIDS` in `avocado_tegraflash/usb.py`. A declared id that is neither
never matches, and the flash waits 60 seconds and fails with "Device did not
enter RCM mode". For an id outside that list, add it to `RECOVERY_PIDS` too.

`meta-avocado-nvidia/stone/tegra/tests/test_manifest_contract.py` compares
this key list with the manifest template, so a key added in one place and not
the other fails a test.

## 2. The engine entry

Add this line to the manifest's `images` object:

```json
"tegraflash_engine": "tegraflash-engine"
```

The value is the literal `tegraflash-engine`, the directory name the deploy
recipe `meta-avocado-nvidia/recipes-bsp/tegraflash/tegraflash-engine.bb`
installs. Stone copies only what a manifest names, so an engine that merely
sits beside the script in the deploy directory never reaches the stone output
directory where the script runs. The shim looks for the engine only in the
data directory.

The board count is a literal in several test files, not one constant; the
list is in section 5. `test_manifest_entries.py` also fails for any manifest
that names the script and lacks this entry. The host door refuses a template
whose value is not `tegraflash-engine` and an engine directory that lacks
`avocado_tegraflash/__main__.py`, because the shim needs both.

## 3. The recovery id (manifest only)

There is no registry step. The recovery id and its evidence live only in the
manifest (`tegraflash.rcm_ids`, `tegraflash.rcm_evidence`, section 1).
`scripts/tests/launch/test_boards_manifests.py` and the engine's manifest tests
validate them, and a recovery id recorded there must also be recognised by the
engine, so its product id has to be listed in `RECOVERY_PIDS` in
`meta-avocado-nvidia/stone/tegra/avocado_tegraflash/usb.py`.

When nobody has seen the board in recovery mode, omit the id and the evidence.
`python3 scripts/avocado-flash boards` then lists the board as `none recorded`,
and an unattended run is refused unless the caller sets
`AVOCADO_PROVISION_RCM_ID=<vendor:product>`.

## 3a. Adding a non-Jetson board

A board that writes an SD card, eMMC or a USB mass storage export is added the
same way: a stone profile plus a manifest entry. There is no Python table to
edit.

1. Write `stone-provision-<medium>.sh`, source the library
   `meta-avocado-distro/stone/avocado-safe-disk.sh` from the script's own
   directory, and call its guards (`avocado_safe_disk_modes`,
   `avocado_safe_disk_check_device`, `avocado_safe_disk_confirm`,
   `avocado_safe_disk_run` and the rest). The i.MX93 ums profile,
   `meta-avocado-nxp/stone/avocado-imx/stone-provision-ums.sh`, is a short
   example.
2. Name the profile in the manifest's `provision.profiles`, and list the
   library in the manifest's `provision.files` (`"files": ["avocado-safe-disk.sh"]`),
   or stone does not copy it next to the script.
3. Declare `"config": { "dry_run": true }` on the profile only if the script
   honours `AVOCADO_PROVISION_DRY_RUN=1`, which it does by running every guard
   through the library and letting it print each target-changing command
   instead of running it. A declaration on a script that ignores the variable
   would let a "dry run" write the disk.
4. Keep the confirmation behaviour in the library. The confirmation table is
   `meta-avocado-distro/stone/tests/confirm-vectors.tsv`; the library's test
   (`meta-avocado-distro/stone/tests/test-avocado-safe-disk.sh`) and the
   engine (`avocado_tegraflash/confirm.py`) both read it, so a new rule is
   one row and not two edits. Today: `AVOCADO_PROVISION_FORCE=1` skips the
   retype; `0` retypes on a terminal and refuses without one; unset or empty
   retypes on a terminal and proceeds without one; any other value refuses; a
   dry run proceeds without a retype.

## 4. The parity matrix

`meta-avocado-nvidia/stone/tegra/tests/parity/` proves the engine equivalent
to the frozen legacy script, which is kept there as the oracle. The cases are
derived from the manifests that name the script (`cases.py`), so a new
manifest adds its profile cases with no case-list edit: every profile of the
manifest, plus scenario cases such as a carrier overlay, a boardctl failure and
a missing input. Two tests pin literal counts and must be updated to match
(see section 5): `test_cases.py` states the manifest count and the total of
profile cases (32 today), and `test_fixtures.py` states the manifest count.

The run prints `cases: N/M run`, and CI
(`.github/workflows/flash-tools-tests.yml`) fails when fewer cases ran than
were planned. The oracle needs `jq`, so install it locally; without it the
cases count as not run and the shortfall check fails.

## 5. Check your work

First update every literal board count; adding a board changes all of them,
and the tests below fail until each one is edited:

| File | What to change |
|------|----------------|
| `meta-avocado-nvidia/stone/tegra/tests/test_manifest_entries.py` | `EXPECTED_MANIFESTS` |
| `meta-avocado-nvidia/stone/tegra/tests/parity/test_cases.py` | `len(stems) == 7` in `test_every_manifest_naming_the_script_is_covered`, and the profile-case total (`32`) in `test_profile_cases_total_32_from_manifest_data` |
| `meta-avocado-nvidia/stone/tegra/tests/parity/test_fixtures.py` | `len(MANIFESTS) == 7` in `test_scan_finds_all_seven_manifests` |
| `scripts/tests/boards/test_registry.py` | the machine list in `test_registry_has_the_seven_jetson_machines` (registry tests go away with the registry) |
| `scripts/tests/boards/test_boards_command.py` | `len(lines) == 7` in `test_boards_lists_seven_lines_with_orin_nano_id` (same) |

The launcher tests under `scripts/tests/launch/` need no edit for a new
manifest: they read the manifests and validate the recovery ids.

Run the two test trees in separate invocations. `test_profile.py` exists in
both, and one pytest run over both trees stops on the duplicate module name.

```bash
python -m pytest scripts/tests -q
python -m pytest meta-avocado-nvidia/stone/tegra/tests -q
```

List the boards. The board must appear with its recovery id or
`none recorded`:

```bash
python3 scripts/avocado-flash boards
```

```text
avocado-icam-540 tegra none recorded
avocado-jetson-agx-orin tegra none recorded
avocado-jetson-agx-thor tegra none recorded
avocado-jetson-orin-nano tegra 0955:7523
```

Then run the engine up to the point where it would flash, with no board
attached. This prepares the work directory and stops
(`AVOCADO_PROVISION_DRY_RUN=1` does the same):

```bash
AVOCADO_STONE_MANIFEST=<deploy>/stone-<machine>.json \
AVOCADO_STONE_DATA_DIR=<deploy> \
AVOCADO_STONE_BUILD_DIR=<scratch> \
AVOCADO_PROVISION_PROFILE=tegraflash-nvme \
<deploy>/stone-provision-tegraflash.sh --prepare-only
```

The output ends with the work directory and `./initrd-flash --erase-nvme`,
the command a real run would execute.

## Deviations from the legacy script

The engine reproduces the legacy script's output files and commands except
for a short list of named deviations, marked in the tests with
`@pytest.mark.deviation("<name>")`. The full list, with what each one changes,
is the "Deviations from the legacy script" section of the
[engine README](../meta-avocado-nvidia/stone/tegra/avocado_tegraflash/README.md);
the five that change what a user sees appear by name in the table below.

## Breaking changes

This section is the release note for the move to the shared engine.

| Change | Who it affects | What to do |
|--------|----------------|------------|
| The provisioning script refuses to run without root, except with `--prepare-only` (`root-check-first`) | Anyone who ran it as a normal user and relied on a later failure | Run it as root, or through `sudo` |
| An unknown profile name is refused and the five accepted names are listed; it used to flash NVMe (`unknown-profile-refused`) | A downstream manifest with a custom profile name | Rename the profile to one of the five names in section 1 |
| More than one board in recovery mode is refused (`one-board-only`) | A lab that relied on `initrd-flash` picking one of several | Disconnect the other boards |
| Carrier values are written literally; a value with `&` or a backslash and a digit used to be corrupted (`carrier-values-literal`). A `carrier.env` with no `CARRIER_LABEL` line no longer aborts the script silently | Carrier authors | Nothing for correct files; add a `CARRIER_LABEL` line so the provision log names the carrier |
| A missing `mkbootimg`, or a failing boot image helper, raises an error naming the cause; the legacy script exited silently | Anyone debugging a failed flash | Read the error text; install the named tool |
| The boardctl target and serial are single arguments (`boardctl-single-arguments`) | A boardctl target or serial containing whitespace, which used to be split | Nothing; the value now arrives whole |
| A named device no longer skips the retype; only `AVOCADO_PROVISION_FORCE=1` does. With no terminal and no signal the run proceeds with a notice, and `AVOCADO_PROVISION_FORCE=0` with no terminal refuses | Anyone who passed an explicit device to skip the prompt, and unattended runs | Set `AVOCADO_PROVISION_FORCE=1` where skipping is intended |
| The engine refuses a run with no pinned kernel, and an unattended run for a board with no declared recovery id | Downstream manifests and lab scripts | Pin the kernel, or set `AVOCADO_PROVISION_ALLOW_UNPINNED_KERNEL=1`; declare `rcm_ids` or set `AVOCADO_PROVISION_RCM_ID` |
| `AVOCADO_FLASH_LAUNCHER=1` routes `avocado-flash` through the stone-profile launcher (opt-in; the default flip is planned by this change) | Anyone driving `avocado-flash` | Nothing yet |
| `avocado-flash nvme` requires python3 3.10 or newer, `cpp`, `fdtget`, `fdtput` and `lsusb` on the host, and no longer needs `jq`. It requires the engine directory in the deploy tree | Everyone using the host door | Install the tools; rebuild an older image tree with the `avocado-stone` target (it is refused with that message) |
| An image tree built before this change keeps the old 694-line script, and none of the new refusals apply to it | Anyone running an old tree | Nothing; reverting the series restores the old behaviour everywhere |

Smaller differences that are not listed deviations, from the engine README:

- A stock `DefaultBootPriority` value ending in a comma keeps its trailing empty field.
- `EXTERNAL_ROOTFS_DRIVE` is written unquoted, exactly as the legacy script writes it. This is not a change.

## Roadmap

Later phases, in order. Nothing in this change does any of them.

1. Port the two OE4T helper scripts into the engine. This needs a module-SKU table and test vectors taken from third-party fixes.
2. Fold the other families' stone scripts behind the registry, deduplicating the byte-identical copies.
3. Fold the launcher's media and the remote-eMMC package into the same registry.
4. Unify the two recovery-mode definitions once every machine has a verified recovery id.
5. Backport to scarthgap.
