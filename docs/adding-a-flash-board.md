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
- A registry entry in `scripts/avocado_flash_boards/tegra.py`, which the host
  door uses to find the board's USB recovery id. This step is retiring: the
  engine reads the id from the manifest (`tegraflash.rcm_ids`), and the
  registry stays only until the wrapper is removed.

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
| `tegraflash.rcm_ids` | List of lowercase `vendor:product` USB ids this board may show in recovery mode; the engine refuses a recovery device whose id is not listed. It narrows the match only: a device still has to be recognised as a recovery device first (see below). Optional: without it the engine warns that the board is not identity-checked and proceeds with exactly one device |

Add the recovery ids you observed on hardware to `tegraflash.rcm_ids` in the
manifest, for example `"rcm_ids": ["0955:7523", "0955:7623"]` (the two Orin Nano
modules). Leave the list out until someone has seen the board in recovery mode.

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

## 3. The registry entry (retiring)

The recovery id now lives in the manifest as `tegraflash.rcm_ids` (section 1),
and the engine checks it there. The host-door registry is retiring: it is
still kept in step with the manifests by
`scripts/tests/boards/test_manifest_sync.py` until the wrapper is removed, and
it is no longer the only place an id lives. Until then, add the entry too.

Add a `Board` to the list in `scripts/avocado_flash_boards/tegra.py`:

```python
Board("avocado-<name>", "tegra", "0955:xxxx", "evidence text"),
```

The fields, from `scripts/avocado_flash_boards/__init__.py`:

| Field | Meaning |
|-------|---------|
| `machine` | The machine name, `avocado-` plus the manifest's `<name>` |
| `family` | `tegra` |
| `rcm_id` | The USB `vendor:product` the board shows in recovery mode, or omitted |
| `rcm_evidence` | Where the id came from |

The evidence rule: record a recovery id only when someone saw it on hardware,
and put what was seen in the evidence text, for example the `lsusb` line
observed. The registry is validated the first time a command reads it, and it
refuses:

- a family that has no module in `scripts/avocado_flash_boards/` exporting
  `VENDOR` (the USB vendor of its recovery ids) and `BOARDS`;
- an id that is not a lowercase `vendor:product` hex pair;
- an id whose vendor is not the family's `VENDOR` (`0955` for `tegra`);
- an id with empty evidence;
- a duplicate machine.

One bad entry stops `avocado-flash nvme` and `avocado-flash boards` (every
command that reads the registry) with a one-line refusal naming the entry, not
just one flash.

A recovery id recorded here must also be recognised by the engine, so its
product id has to be listed in `RECOVERY_PIDS` in
`meta-avocado-nvidia/stone/tegra/avocado_tegraflash/usb.py`;
`scripts/tests/boards/test_registry.py` fails, naming the board and the missing
product id, when it is not.

When nobody has seen the board in recovery mode, omit the id and the evidence.
`avocado-flash boards` then lists the board as `none recorded`, and the host
door refuses it unless the caller passes `--rcm-id <vendor:product>`. Guessing
an id would let the flash pin a different device, so an unknown id stays
unknown.

`scripts/tests/boards/test_manifest_sync.py` fails when a Jetson manifest has
no registry entry, or a registry entry has no manifest, and its message names
the `stone-<name>.json` files and the orphaned machines. It holds no count, so
adding the manifest and the entry together passes it. The other board-count
places are listed in section 5.

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
| `scripts/tests/boards/test_registry.py` | the machine list in `test_registry_has_the_seven_jetson_machines` |
| `scripts/tests/boards/test_boards_command.py` | `len(lines) == 7` in `test_boards_lists_seven_lines_with_orin_nano_id` |

`scripts/tests/boards/test_manifest_sync.py` needs no edit: it compares the
manifests with the registry and names any difference.

Run the two test trees in separate invocations. `test_profile.py` exists in
both, and one pytest run over both trees stops on the duplicate module name.

```bash
python -m pytest scripts/tests -q
python -m pytest meta-avocado-nvidia/stone/tegra/tests -q
```

List the registry. The board must appear with its recovery id or
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
attached. This prepares the work directory and stops:

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
