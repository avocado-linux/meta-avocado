# Consumers of the security-capability declaration

This file records the enumeration behind assumption A5 of the
`var-key-provider-deliverability-check` change: that nothing already shipped
depends on Raspberry Pi declaring `encrypted-var`.

Scope of the enumeration: both readers of the declaration, namely the BitBake
variable `AVOCADO_SECURITY_CAPABILITIES` and the runtime artifact
`/etc/avocado-security-capabilities`, which
`meta-avocado/classes/avocado-security-capabilities.bbclass` writes into the
rootfs AND the initramfs.

Branch enumerated: `boot-integrity-poc`, at the tree state of this commit.
`origin/wrynose` was checked separately for the Pi declaration line and agrees.

## Headline result

A5 holds. No consumer expects Raspberry Pi to carry `encrypted-var`.

It holds in a stronger form than the design anticipated: **the Pi already
declares nothing.** `meta-avocado-raspberrypi/conf/machine/include/avocado-raspberrypi.inc:27`
reads `AVOCADO_SECURITY_CAPABILITIES = ""`, with a comment naming the two
missing pieces (no dm-crypt fragment in `linux-raspberrypi`, no `var` PARTLABEL
in the MBR layout). Commit `0f20494c` ("security: build declared capabilities
into the feed, let the runtime choose") replaced the earlier
`AVOCADO_SECURITY_CAPABILITIES = "encrypted-var"` with the empty string. The
design's premise that the Pi still declares `encrypted-var` at line 17 is stale;
task 3.1 of this change is already satisfied on this branch.

## Consumers found

### Build-time: the enforcement and artifact-writing class

| Location | What it does with the declaration |
|---|---|
| `meta-avocado/classes/avocado-security-capabilities.bbclass:79` | `bb.event.ConfigParsed` check: refuses a build whose requested feature is absent from the declaration. Distinguishes unset from empty. |
| `meta-avocado/classes/avocado-security-capabilities.bbclass:178` | `avocado_security_capabilities_write_artifact`, which writes `${IMAGE_ROOTFS}${sysconfdir}/avocado-security-capabilities`. Returns early when the variable is unset, so an unmigrated machine gets no file. |
| `meta-avocado/conf/distro/include/avocado-security.inc:32` | `INHERIT += "avocado-security-capabilities"`, making the class global. |

### Build-time: the two images that hook the artifact writer

Both are needed, and the initramfs is the first consumer at runtime.

| Location | Note |
|---|---|
| `meta-avocado/recipes-avocado/images/avocado-image-rootfs.bb:43,52` | `ROOTFS_POSTPROCESS_COMMAND` hook plus `do_rootfs[vardeps]`. |
| `meta-avocado/recipes-avocado/images/avocado-image-initramfs.bb:64,69` | Same hook. `cryptsetup-var.service` is an initrd unit, so this copy is the one read on boot. |

### Build-time: recipes gating content on the declaration

| Location | Gate |
|---|---|
| `meta-avocado/recipes-avocado/packagegroups/packagegroup-avocado-rootfs.bb:57,64` | Always ships `avocado-security-capabilities`; ships `cryptsetup-var-udev cryptsetup cryptsetup-var-posture` on `encrypted-var`. |
| `meta-avocado/recipes-avocado/packagegroups/packagegroup-avocado-initramfs.bb:9,14` | Same shape for the initramfs: `cryptsetup cryptsetup-var` on `encrypted-var`. |
| `meta-avocado-nvidia/recipes-avocado/packagegroups/packagegroup-avocado-tegra-extra.bb:51,52` | `encrypted-var` and `ftpm` gates for Jetson. |
| `meta-avocado/recipes-kernel/linux/linux-yocto_%.bbappend:21` | Adds `file://dm-crypt.cfg` on `encrypted-var`. Note this is `linux-yocto`; the Pi builds `linux-raspberrypi`, which has no such bbappend. |
| `meta-avocado/recipes-security/optee-ftpm-init/optee-ftpm-init.bb:132` | Recipe-level assertion that a machine installing the fTPM declares `ftpm`. Precedent for the recipe-level check task 2.2 adds. |
| `meta-avocado/recipes-security/avocado-security-capabilities/avocado-security-capabilities.bb:24,27,29` | Packages the declaration into `/etc/avocado-security-capabilities`. A second writer of the same path, alongside the bbclass postprocess. |

### Runtime: readers of `/etc/avocado-security-capabilities`

| Location | Capability it looks for | Behaviour on absence |
|---|---|---|
| `meta-avocado/recipes-core/cryptsetup-var/files/cryptsetup-var.sh:43-55` | `encrypted-var` | Fails closed with a diagnostic. |
| `meta-avocado/recipes-security/optee-ftpm-init/files/optee-ftpm-setup.sh:31-43` | `ftpm` | Fails closed with a diagnostic. |

Both are machine-agnostic: they read whatever the file says. Neither hardcodes a
machine name, so neither can expect the Pi to declare anything in particular.

### Tests that synthesise the artifact

These write the file themselves rather than consuming a machine's declaration,
so they are unaffected by any machine's declaration changing.

- `meta-avocado/recipes-core/cryptsetup-var/tests/test-cryptsetup-var-inplace.sh:107,308`
- `scripts/test-security-capability-guards.sh:93,102,121`

### Machine declarations (writers, listed for completeness)

`meta-avocado-nvidia/conf/machine/include/avocado-jetson.inc:17`,
`meta-avocado-nxp/conf/machine/avocado-imx8mp-evk.conf:62`,
`meta-avocado-nxp/conf/machine/avocado-imx93-frdm.conf:161`,
`meta-avocado-qemu/conf/machine/avocado-qemuarm64.conf:54`,
`meta-avocado-qemu/conf/machine/avocado-qemux86-64.conf:63`,
`meta-avocado-x86-64/conf/machine/avocado-intel-x86-64-v2.conf:30`,
`-v3.conf:31`, `-v4.conf:36`,
`meta-avocado-raspberrypi/conf/machine/include/avocado-raspberrypi.inc:27` (empty).

### Documentation

`docs/security-capabilities.md` and `docs/adding-a-machine-target.md` describe
the mechanism. The machine table at `docs/security-capabilities.md:272` already
records `raspberrypi*` as declaring `""`, and line 175 already states why. No
doc claims the Pi delivers `encrypted-var`.

## Sibling repositories: no consumers found

No file in any sibling repository under `/home/tiamarin/repos/work/peridio/`
mentions `AVOCADO_SECURITY_CAPABILITIES` or `avocado-security-capabilities`, and
no file outside `meta-avocado/` mentions `encrypted-var` at all. The searched
set is every directory listed by `ls /home/tiamarin/repos/work/peridio/`,
including `avocado-cli`, `avocadoctl`, `avocado-conn`, `avocado-rat`,
`avocado-config`, `avocado-desktop`, `stone`, `peridiod`, `meta-peridio`,
`docs`, `references`, `rubicon` and `rubicon-tests`.

## Limits of this enumeration

Stated so a clean result is not read as broader than it is.

- **Text search only.** A consumer that constructs the path at runtime from
  fragments, or that reads it from a compiled binary with no matching source in
  this workspace, would not be found.
- **`grep -I` skips binary files.** A precompiled artifact shipped without
  source is out of reach.
- **Generated build output was excluded** (`tmp`, `build*`, `sstate-cache`,
  `downloads`). Those contain generated copies of the artifact, not consumers.
- **One workspace, one branch.** Repositories not checked out here, and
  customer or downstream layers outside this tree, were not searched. A
  downstream layer could in principle expect the Pi to declare `encrypted-var`;
  nothing in this tree does.

## Search commands

Run from `/home/tiamarin/repos/work/peridio/meta-avocado` unless noted.

```bash
# Both readers, inside this layer repository.
grep -rn --exclude-dir=.git "AVOCADO_SECURITY_CAPABILITIES" .
grep -rn --exclude-dir=.git "avocado-security-capabilities" .
grep -rn --exclude-dir=.git "CAPABILITIES_FILE" .

# Any Pi-specific expectation of the capability.
grep -rn --exclude-dir=.git "encrypted-var" . | grep -i -e raspberry -e rpi -e pi5 -e pi4

# Sibling repositories, run from /home/tiamarin/repos/work/peridio.
grep -rIn --exclude-dir=.git --exclude-dir=node_modules --exclude-dir=target \
  --exclude-dir=tmp --exclude-dir=build --exclude-dir=sstate-cache \
  --exclude-dir=downloads \
  -e 'avocado-security-capabilities' -e 'AVOCADO_SECURITY_CAPABILITIES' . \
  | grep -v '^\./meta-avocado/'

# The Pi declaration, current and historical.
sed -n '21p' meta-avocado-raspberrypi/conf/machine/include/avocado-raspberrypi.inc
git log -p -- meta-avocado-raspberrypi/conf/machine/include/avocado-raspberrypi.inc \
  | grep -n 'AVOCADO_SECURITY_CAPABILITIES'
git show origin/wrynose:meta-avocado-raspberrypi/conf/machine/include/avocado-raspberrypi.inc \
  | grep -n 'AVOCADO_SECURITY_CAPABILITIES'
```

## Consequences for the rest of the change

- Task 3.1 has nothing to do on this branch. The declaration is already `""`
  and already carries a comment naming the return condition. Confirm before
  editing rather than re-applying the change.
- Task 4.1 wants a Pi build refused by the new deliverability check. Because the
  Pi declares nothing, that build is refused by the existing bbclass check
  first, exactly as task 4.1 anticipates. A machine that declares
  `encrypted-var` and resolves to the shared provider has to be constructed
  separately to exercise the new check.
- There is no `kas/feature/encrypted-var.yml` in this tree, though the handoff's
  E2E invocations name one. It does not need replacing: since commit `e49c8670`
  the check gates on the machine's `AVOCADO_SECURITY_CAPABILITIES` declaration,
  not on `DISTRO_FEATURES`, so arming it means selecting a machine that DECLARES
  the capability rather than injecting a feature token. `encrypted-var` is a
  retired `DISTRO_FEATURES` token that no machine sets and that
  `avocado-security-capabilities.bbclass` warns about when it appears.

## The var-key provider contract

A machine that declares `encrypted-var` must resolve to a `var-key.sh` that can
actually derive a key. Two tiers enforce that, and a provider has to satisfy
both.

### What a provider must carry

```sh
# avocado-var-key-provider: usable
# avocado-var-key-identity: /sys/devices/soc0/serial_number
ROOT="${1:-}"
SOC_UID_FILE="$ROOT/sys/devices/soc0/serial_number"
```

- Exactly one `avocado-var-key-provider:` line, `usable` or `unusable`.
- One `avocado-var-key-identity:` line per file the provider reads its hardware
  identity from, each an absolute path.
- Every one of those reads prefixed with the script's optional first argument.
  `cryptsetup-var.sh` invokes the provider with no arguments, so on a device the
  prefix is empty and each path resolves to the real absolute one.

Both marker lines are matched as declarations, not as prose: exactly one leading
`#` is stripped, so an indented documentation example showing the contract is
not itself read as declaring it.

### Tier 1, parse time (`python __anonymous`)

Resolves the winning provider on `FILESPATH` and reads its status line. Refuses
before anything is fetched or compiled. This is the only tier that reads the
`FILESPATH` source rather than the installed artifact, and the only one that
names the deliberate `unusable` placeholder distinctly instead of reporting a
generic failure.

### Tier 2, install time (`do_install[postfuncs]`)

Runs the INSTALLED provider under `${D}` against two synthetic identity
fixtures built from its declared paths, and requires each run to exit 0 with 64
bytes and the two keys to DIFFER.

The two-identity part is the load-bearing half. A length check alone passes a
provider that emits a hardcoded constant, and passes one whose identity read is
missing its `ROOT` prefix and so resolves against the build host's own `/sys`
instead of the fixture. Both return the same key twice; neither is visible from
a single run. Both are the fleet-wide-identical-key failure the providers'
own comments say they exist to prevent.

### What the check does not establish

- **That the identity is readable on the device at initramfs time.** That is a
  property of the target's kernel config and boot path. No build-time check
  reaches it; only a boot does.
- **That the device's openssl matches the build host's.** The check derives with
  `openssl-native`; the device uses target `openssl-bin`, and
  `openssl kdf ARGON2ID` requires OpenSSL 3.2 or newer. A layer pinning the
  target older than the native passes here and fails at first boot.
- **That any branch other than the declared one works.** Only declared paths are
  populated, so a fallback leg is never walked. The qemu provider is the live
  example: on `avocado-qemux86-64` the branch the device actually takes is the
  `/proc/cpuinfo` one, which ends in the constant `qemu-no-serial`, and the
  check exercises the device-tree branch instead.
- **That the provider is still the one checked.** Tier 2 reads `${D}`, which
  closes the `do_install:append` window. It does not close the postfunc window:
  a bbappend appending its own `do_install` postfunc runs after this one.

### Adding a machine

Copy the nearest existing provider rather than the shared one under
`meta-avocado/` - that one is marked `unusable` deliberately, because it reads a
secret from `/var/private/`, which is inside the very volume being unlocked and
which nothing in this tree provisions.
