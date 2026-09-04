# Task 4.1: deliverability refusal, observed live

Confirms the scenario the whole change exists for: a machine that declares
`encrypted-var` but resolves to a var-key provider that cannot derive a key is
REFUSED at build time by `cryptsetup-var.bb`'s check, not silently built.

## Why a scratch machine is required

No real machine in the tree satisfies both halves. Every machine that declares
`encrypted-var` also supplies its own provider:

| Machine | Declares `encrypted-var` | Provider override |
|---|---|---|
| `avocado-imx93-frdm`, `avocado-imx8mp-evk` | yes | `meta-avocado-nxp` (`:avocado-imx`) |
| `avocado-qemuarm64`, `avocado-qemux86-64` | yes | `meta-avocado-qemu` (exact names) |
| Jetson (`avocado-jetson.inc`) | yes | `meta-avocado-nvidia` (`:tegra`) |
| `avocado-raspberrypi*` | no (`""`) | none |
| `avocado-intel-x86-64-v*` | no (`tpm2` only) | `meta-avocado-x86-64` |

So the combination has to be constructed. That is the point of the check: it
guards a state the tree is currently free of, and which any new machine would
reach by declaring `encrypted-var` without shipping a provider of its own -
Jetson was the target that prompted the work.

## Construction

Two temporary files, both deleted after the run:

- `meta-avocado-qemu/conf/machine/avocado-qemux86-64-nodeliv.conf` - a single
  `require conf/machine/avocado-qemux86-64.conf`. It inherits that machine's
  `AVOCADO_SECURITY_CAPABILITIES = "encrypted-var tpm2"` verbatim, but because
  the MACHINE name differs, `meta-avocado-qemu`'s
  `FILESEXTRAPATHS:prepend:avocado-qemux86-64` (keyed on the exact name) does
  not apply, so `cryptsetup-var`'s `FILESPATH` lookup falls through to the
  shared, sentinel-carrying `var-key.sh`.
- `kas/machine/qemux86-64-nodeliv.yml` - the qemux86-64 kas machine file with
  `machine:` repointed.

Nothing else was changed. Note what is NOT here: the first, void attempt at
this task also had to append `encrypted-var` to `DISTRO_FEATURES` by hand,
because the check then gated on a token no machine sets. After `e49c8670`
re-gated it on `AVOCADO_SECURITY_CAPABILITIES`, the declaration alone arms it -
which is the whole point, since that is what real machines actually set.

## Command

```
bakar bitbake -c install cryptsetup-var meta-avocado/kas/machine/qemux86-64-nodeliv.yml
```

Run from `/home/tiamarin/repos/work/peridio` on `bakar 0.29.2 (cd4619e8eae7)`.
Run locally rather than dispatched, and scoped to `-c install`, because the
refusal is a parse-time one: it fires before any task runs, so nothing is
gained by building the recipe's full runtime closure on the remote builder.

## Result: REFUSED

Parsing halted, no image produced. The exact message, from the run log at
`build-qemux86-64-nodeliv/build/runs/20260903-181908/kas.log`:

```
ERROR: .../meta-avocado/recipes-core/cryptsetup-var/cryptsetup-var.bb: machine
avocado-qemux86-64-nodeliv declares encrypted-var but the var-key.sh that
resolves for it (.../meta-avocado/recipes-core/cryptsetup-var/files/var-key.sh)
declares itself unusable: it is the placeholder that cannot actually derive a
key. Ship a var-key.sh for this machine carrying the comment line '#
avocado-var-key-provider: usable' and able to derive a device-unique key. It
must also carry one '# avocado-var-key-identity: <absolute path>' line per file
it reads its hardware identity from, and prefix every one of those reads with
the script's optional first argument, so the build-time check can derive against
a synthetic identity - see README-deliverability.md. A var-hwkey.sh does not
satisfy any of this on its own: per cryptsetup-var.sh it supplies the passphrase
of a SECOND keyslot and leaves the var-key.sh keyslot as the recovery path, so a
machine with only a hwkey backend still cannot derive that recovery key.
ERROR: Parsing halted due to errors, see error messages above
```

## Confirmation this is the NEW check

- **Attributed to the recipe**: the ERROR is prefixed with the path to
  `cryptsetup-var.bb`, where the anonymous python lives.
- **Names the machine**: `avocado-qemux86-64-nodeliv`, verbatim.
- **Names the feature**: `encrypted-var`.
- **Names the resolved provider**, so which file was judged is not left to
  inference: the shared `meta-avocado/.../files/var-key.sh`.
- **The bbclass diagnostics are absent.** Grepping the run log for the three
  strings `avocado-security-capabilities.bbclass` emits - `requested security
  feature`, `declares no AVOCADO_SECURITY_CAPABILITIES`, `not present in its
  AVOCADO_SECURITY_CAPABILITIES` - returns **0** matches. The refusal cannot be
  attributed to the older declaration check.

## Which tier refused, and why it is still this one

The check now has two tiers: this parse-time declaration check, and a
`do_install` tier that executes the installed provider against two synthetic
identities. This machine is refused by the FIRST, and that is the correct
outcome rather than a gap in the second. A provider that declares itself
`unusable` should never reach the point of being run, and refusing at parse
costs nothing - no fetch, no unpack, no task.

The message quoted above is re-recorded from a run made after the execution
tier landed. It changed since the previous recording: the remedy now states the
whole contract, including the identity declarations and the argument prefix the
second tier needs, because naming only the status line sent an author past
parse and into a differently worded refusal one build later.

## Unrelated secondary error, recorded for honesty

The same run also produced
`avocado-slot-root-generator_1.0.bb: Unable to get checksum for ... SRC_URI
entry stone-qemux86-64-nodeliv.json: file could not be found`. That is
collateral of the scratch MACHINE name having no corresponding `stone` config,
not a product of this change. It is independent of the deliverability ERROR,
which is attributed to a different recipe and is what halted parsing.

## Cleanup

Both scratch files were deleted after the run; `git status --short` in
`meta-avocado/` is clean apart from this test file.
