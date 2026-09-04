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

- Exactly one `avocado-var-key-provider:` line, `usable`, `test-only` or
  `unusable`.
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

Runs the INSTALLED provider under `${D}` against synthetic identity fixtures
built from its declared paths. For a provider declaring N paths it performs
`2N + 3` runs and requires:

1. every run to exit 0 with exactly 64 bytes;
2. for EACH declared path, populated ALONE under two different values, the
   derived key to CHANGE;
3. the same identity to yield the SAME key, re-derived once;
4. a path-rewritten copy invoked with NO argument to yield the same key as the
   argv run over the same fixture;
5. an EMPTY fixture to be REFUSED.

Check 2 is the load-bearing one and its shape matters twice over. Populating
every declared path at once was the original form, and it let a provider whose
SECONDARY read is missing its `ROOT` prefix through: the primary resolves,
short-circuits, and the broken read is never walked, so the differential is
satisfied entirely by the good path. Populating one path at a time makes each
declared read the only source of a key.

Comparing keys ACROSS paths - one value per path - is the weaker version and
does not finish the job. An unprefixed read that RESOLVES on the build host
yields `key(fixture)` for the prefixed path and `key(host)` for the broken one:
two different keys, so a cross-path comparison passes while the broken read
never touched the fixture. Changing one path's OWN value and requiring the key
to follow is what proves the provider read that path from that root.

Check 3 looks redundant and is not. A provider mixing in a timestamp or a
random salt satisfies check 2 trivially, because its two runs differ for the
wrong reason - and on a device that is worse than a constant key: first boot
formats `/var` with one key and every later boot derives another, so the volume
never opens again.

Check 4 exists because the device passes no argument. Every other run hands the
provider a fixture root as argv, which `cryptsetup-var.sh` never does, so the
artifact under test could see that it was under test: a provider deriving
properly whenever `$1` was set and emitting a constant when it was empty
satisfied every other check here. Rewriting each declared path into a copy and
running that copy with no argument removes the signal rather than trusting its
absence. It is why a declared path must appear literally in the script - a path
assembled at run time cannot be rewritten, so such a read cannot be shown to
reach the fixture rather than the host.

The empty-fixture run answers a different question: not "does it read its
declared sources" but "what does it do when they are missing on a real device".
A provider that substitutes a constant there derives a perfectly good-looking
64 bytes that every board in the fleet shares, which the differential cannot
see because the constant is reached identically every time.

### Tier 3, image time (`avocado_security_capabilities_check_provider`)

Lives in `avocado-security-capabilities.bbclass` and runs from the initramfs
image's `ROOTFS_POSTPROCESS_COMMAND`, right after the artifact writer. It reads
the capability the IMAGE is about to declare and inspects the `var-key.sh` that
image actually contains, refusing an absent provider, a status count other than
one, `unusable`, an unrecognised status, and `test-only` on a machine outside
the allow-list.

It exists because tiers 1 and 2 cannot check whether they ran. Both read
`AVOCADO_SECURITY_CAPABILITIES` from `cryptsetup-var.bb`'s datastore while
`/etc/avocado-security-capabilities` is written from the image recipe's, so

```bitbake
# cryptsetup-var.bbappend
AVOCADO_SECURITY_CAPABILITIES = ""
```

silenced both tiers while the image went on declaring `encrypted-var` and
installing the provider - and `cryptsetup-var.sh` reads that artifact on the
device, passes, and derives with whatever shipped. Reproduced end to end: with
that bbappend, `do_install` completes with no warning and no fixtures written,
the `unusable` placeholder lands in `${D}`, and the initramfs `do_rootfs` now
fails instead of shipping it.

**Fixed by altitude, not by another variable.** A canonical copy in a second
variable moves the problem rather than removing it, because whoever overrode
the first can override the second. Here the declaration and the shipped
provider are visible in one datastore at one point, so they cannot disagree.

The initramfs and not the rootfs: `packagegroup-avocado-initramfs.bb` installs
`cryptsetup cryptsetup-var` when the capability is declared, while the rootfs
gets only the udev and posture packages, so the initramfs is the image that
carries the provider - and, `cryptsetup-var.sh` being an initrd unit, the one
that consumes it first.

**A status line is not an identity.** Before trusting any declaration, tier 3
requires the provider to match the attestation tier 2 writes beside it -
`var-key.sh.sha256`, the digest of the exact bytes that passed every tier-2
assertion, written last so its presence means "these bytes passed" rather than
"these bytes were seen". Without that, a bbappend registering its own
`do_install` postfunc after `avocado_var_key_check_deliverability` could replace
the validated script with an `exit 1` or a constant-key body carrying the same
`usable` line, and every remaining check would pass it.

A MISSING attestation is the louder case, not the quieter one. Tier 2 writes it
last, so its absence means tier 2 did not finish - and the way it does not
finish is by returning early on a capability this image still declares. The
recipe-datastore bypass is therefore caught twice, by two independent signals.

What the attestation does NOT stop: an edit that updates the digest alongside
the provider. Both live in `${D}` and are equally writable, so this binds
against a postfunc that replaces the provider without knowing the attestation
exists - the accidental and the expedient case, which is the same threat the
image tier was added for. It is not a signature, and one more line defeats it.

It is deliberately NOT a second copy of the derivation check. Tier 2 runs the
provider against synthetic identities and stays the expensive, authoritative
tier; tier 3 answers only the question tier 2 cannot ask about itself - did it
run, and over the provider that shipped - for which the attestation plus a
status read suffices. The
parser, the flattener and the `test-only` allow-list live in the class so both
readers share one implementation; a mutation widening that allow-list turns both
tier 1 and tier 3 red, which is how the sharing is verified rather than assumed.

### The three statuses

| Status | Meaning | Build outcome |
|---|---|---|
| `usable` | Derives a device-unique key, and refuses when no identity is readable | Runs both the differential and the empty-fixture refusal |
| `test-only` | Cannot refuse: it substitutes a constant when no identity is readable | Runs the differential, skips the refusal, and WARNS naming the machine. Only for machines listed in `AVOCADO_VAR_KEY_TEST_ONLY_MACHINES`; refused for any other |
| `unusable` | Placeholder that cannot derive a key at all | Refused at parse time |

`test-only` exists for one situation and should not spread beyond it. A virtual
machine has no unique board identifier, so the qemu provider falls back to
`qemu-no-serial` and every VM built from one image derives the same `/var` key.
That is correct for a disposable evaluation target and disqualifying for
anything shipping to hardware. A machine that ships must resolve to a provider
declared `usable`, which has to earn it by refusing.

It is deliberately not self-service, because it is the one fail-open path here
and everything else fails closed. A provider only ASKS for the waiver; whether a
machine may have it is decided by `AVOCADO_VAR_KEY_TEST_ONLY_MACHINES`, which is
set in `meta-avocado` rather than in the layer shipping the provider. Otherwise
the waiver would be unlocked by editing one comment line in a file the vendor
already owns, turning a refusal into a warning among the thousands an image
build emits. For the same reason the waiver requires the FILESPATH source and
the installed copy to agree: the behavioural checks judge `${D}` because that is
what ships, but a waiver read from `${D}` alone could be granted by a
`do_install:append` that rewrote the status after the parse tier passed.

Do not read a clean build log as proof that no machine is on a `test-only`
provider. The warning is emitted by a `do_install` postfunc, so an sstate hit
skips it, and machines sharing a provider share that sstate object.

### The golden vectors, and why a red one is not re-pinned

Every assertion above is RELATIVE - 64 bytes out, two identities differing, one
identity repeating. All of them survive a change to the KDF parameters, because
the change applies to both sides of each comparison. Measured across the three
vendor suites, six such edits (`iter`, `memcost`, `lanes`, the salt's `cut`
width, its digest, and `ARGON2ID` to `ARGON2I`) left all three suites green,
and so did substituting a constant for either KDF channel: replacing
`pass:"$HW_ID"` still leaves the salt varying per identity, and pinning the
salt still leaves the password varying, so the differential passes both times.
Only `keylen` was already caught, by the 64-byte assertion.

Each suite therefore pins one identity to one key - its last case, run against
the UNMODIFIED provider through the argv fixture root so the vector is wired to
the real derivation rather than to a copy of the openssl invocation. With the
vectors in place all eight of those edits turn their suite red.

**A failing vector is a migration signal, not a stale expectation.** The key
changing means a board whose `/var` was formatted under the old derivation can
no longer unlock it, and the Argon2id keyslot is the recovery path, so there is
nothing behind it. Land the migration first - derive the old key, `luksAddKey`
the new one, `luksKillSlot` the old - and re-pin the vector after. Re-pinning
to make the suite green is how a fleet loses its data with every test passing.

### Whether a derivation change locks a device out

The golden vectors make a changed derivation LOUD. They do not say which inputs
moved, or whether any device can produce one. `tests/compare-derivations.py`
answers that: it runs each provider at two git refs over a table of identity
values and reports every row whose key changed, or whose key became a refusal.
Both sides are driven by rewriting the declared paths and running with no
argument, because a provider from before this check existed takes no first
argument and cannot be pointed at a fixture at all.

```bash
python3 tests/compare-derivations.py <ref-before-the-change> [--provider LAYER]
```

The base ref is required and has no default on purpose. A merge-base against
the remote's default branch does not resolve on a branch with an unrelated
history - `boot-integrity-poc` shares no ancestor with `origin/scarthgap` - and
a wrongly chosen base produces a full table of meaningless rows rather than an
error.

Run it before re-pinning a vector, and read the result with one qualifier: a
row matters only if a device can BOTH produce that input AND already hold a
`/var` formatted under the older ref. Neither half is visible from the table.

Measured for this change (`2830879f` to HEAD), 25 of 39 rows are lockouts:

| Provider | Lockout rows | Preconditions | Reaches a machine declaring `encrypted-var`? |
| --- | --- | --- | --- |
| x86-64 | 13 of 19 | a placeholder in `product_uuid`, including a spacing variant | **No** - all three Intel machines declare `tpm2` only, and the layer has no machine include |
| nxp | 7 of 11 | a whitespace-only, all-zero or all-ones `soc0/serial_number` | **Yes** - `avocado-imx93-frdm`, `avocado-imx8mp-evk` |
| nvidia | 5 of 9 | a whitespace-only, all-zero or all-ones DT `serial-number` | **Yes** - all seven Jetson machines, via `avocado-jetson.inc:17` |

**Enumerate declarations with a search that reaches includes.** An earlier
version of this table said nvidia reached no declaring machine, on the strength
of `grep AVOCADO_SECURITY_CAPABILITIES meta-avocado-nvidia/conf/machine/*.conf`.
That glob does not match `conf/machine/include/`, which is where the Jetson
declaration lives and which all seven machine confs `require`. A second pass
that filtered out lines containing `bb.utils.contains` then dropped
`avocado-imx93-frdm`, whose declaration appends `ftpm tpm2` conditionally. Both
searches returned a clean-looking answer that was wrong in the permissive
direction. The search that works is `git grep AVOCADO_SECURITY_CAPABILITIES`
with no path glob and no filter, reading the assignments out of the result:

```bash
git grep -n 'AVOCADO_SECURITY_CAPABILITIES' | grep 'encrypted-var'
```

Ten machines declare it: seven Jetson, two i.MX, and the two QEMU targets
(which resolve to the `test-only` provider). No x86-64 machine does.

**Two rows are both reachable and plausible, and both are deliberate.** The nxp
and nvidia providers each ship to declaring hardware, and a SoC whose UID fuses
were never provisioned reads `0000000000000000` while an erased one reads
`ffffffffffffffff` - neither is a value the driver refuses to emit, unlike the
whitespace-only case. Such a board previously derived a key from that constant,
which means every board of that model in the same state shared it. Refusing is
the correct outcome and locking the volume is the cost of removing a fleet-wide
key; the alternative is keeping it. Exposure is nil today only because no
device is fielded with `encrypted-var` at all - no machine that declares it has
a runtime enabling `var.encrypt`. That is a fact about the fleet, not a
property of the code, and it is the only thing standing between this change and
a migration requirement.

The x86-64 rows do not intersect: they are the most plausible inputs, since
whitebox boards really do ship those placeholder strings, but that provider
reaches no machine with the capability enabled. The whitespace-only rows reach
shipping hardware and need a primary identity holding only blanks, which the
i.MX and Tegra SoC drivers do not emit.

Worth noting where the review pressure landed, because it is a trap for the
next reader: this was raised against x86-64, the provider with the largest
key-change surface and no reachability, and it did not mention nxp, the only
one that ships. Surface size and exposure are independent, and the table above
is arranged to keep them apart.

**No migration is a conclusion about this change, not a standing property.** A
future provider edit can land in the reachable-and-plausible cell, and by then
a device may hold a volume. The sequence is: golden vector goes red, run this
tool, and if any lockout row is reachable and plausible, land the migration in
`cryptsetup-var.sh` first - derive the old key, `luksAddKey` the new one,
`luksKillSlot` the old, reusing the machinery already there for the TPM
keyslot - and re-pin the vector after.

### What the check does not establish

- **That the identity is readable on the device at initramfs time.** That is a
  property of the target's kernel config and boot path. No build-time check
  reaches it; only a boot does.
- **That the device's openssl matches the build host's.** The check derives with
  `openssl-native`; the device uses target `openssl-bin`, and
  `openssl kdf ARGON2ID` requires OpenSSL 3.2 or newer. A layer pinning the
  target older than the native passes here and fails at first boot.
- **That an UNDECLARED branch works.** Every declared path is now exercised on
  its own, so a declared fallback leg is walked rather than shadowed. A branch
  the provider never declares is still unreached. The qemu provider is the live
  example: on `avocado-qemux86-64` the branch the device actually takes is the
  `/proc/cpuinfo` one, which ends in the constant `qemu-no-serial`, and it
  declares only the device-tree path. The remedy is to declare every path read,
  not to widen the check.
- **That the provider is still the one checked.** Tier 2 reads `${D}`, which
  closes the `do_install:append` window. It does not close the postfunc window:
  a bbappend appending its own `do_install` postfunc runs after this one.
- **That either tier ran at all.** Both read `AVOCADO_SECURITY_CAPABILITIES`
  from this recipe's own datastore, so a one-line `cryptsetup-var.bbappend`
  clearing it silences both - and always will, because that is the datastore
  they are parsed in. That is now caught one level up rather than here; see the
  third tier below.

### The tier regression test

`tests/test-var-key-tiers.py` beside this file runs BOTH tiers outside a build.
It slices the two `python ...() { }` bodies out of this recipe at run time and
execs them against stubbed `bb` and `d`, so it exercises the shipped code rather
than a copy - a copy would be edited alongside the recipe and stay green, which
is the regression it exists to catch. Run it with `python3`; it needs only an
OpenSSL carrying ARGON2ID and skips itself without one.

Each refusal case asserts a substring of ITS OWN branch's message, not merely
that the tier refused, and that distinction is the file's main lesson. The
guards are layered, so disabling one lets a downstream guard refuse the same
synthetic provider while a verdict-only assertion stays green. Measured, 6 of 13
recipe mutations survived exactly that way before the message assertions went
in: tier 1's `unusable` fatal fell through to its unrecognised-status check, the
two-identity differential fell through to the negative control, and both the
escape guard and the returncode check fell through to the 64-byte check. With
the assertions, 18 of 18 mutations turn the file red.

The trap recurs whenever a message is edited. Adding "when run against %s" to
the 64-byte diagnostic made it share a substring with the returncode
diagnostic, and the returncode mutation went green again until three cases were
repointed at a fragment only that branch carries. When editing a tier's message,
re-run the mutation battery rather than only the suite.

The same effect caught a wrong assumption in one of its own cases. An unprefixed
read of a declared path that resolves NOWHERE on the build host refuses, so it
is caught by the returncode branch several guards before the differential. To
reach the differential the unprefixed path has to exist on the host, which is
why one case declares `/proc/sys/kernel/ostype` rather than a synthetic `/sys`
path - and why the two are separate cases.

It covers all three tiers, slicing the two recipe bodies from
`cryptsetup-var.bb` and the image-scope one from the class, with the shared
helpers sliced from the class too.

No gaps are open. Four were recorded this way and all four are closed - a
secondary read shadowed by the primary, a provider that derived only when
handed a fixture root, and the capability bypass on each of the two recipe
tiers. The mechanism stays: a hole gets a case that asserts today's wrong
answer and names the change that would fix it, and the expectation flips when
that change lands.

Five cases run the tier against the REAL shipped providers rather than a
synthetic one. They cover the direction that breaks a build rather than the one
that lets a bad provider through: every time this tier gets stricter it can
start refusing an artifact that was fine, and neither the per-path fixture nor
the literal-path requirement is visible from reading a provider.

### Not covered by an executable test

The three `test-deliverability-*.md` files beside this one are records of builds
that were run, not tests a runner re-executes.

What the tier test above cannot reach is BitBake itself. It stubs
`bb.utils.contains`, so it judges the capability gate's LOGIC and not the
datastore that gate reads - which is precisely where C5 lives. That bypass was
confirmed on a real build rather than here, and no amount of stubbing would have
found it. An oe-selftest remains the only way to cover the datastore boundary.

### Adding a machine

Copy the nearest existing provider rather than the shared one under
`meta-avocado/` - that one is marked `unusable` deliberately, because it reads a
secret from `/var/private/`, which is inside the very volume being unlocked and
which nothing in this tree provisions.
