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
guards a state the tree is currently free of, and which a new target - Jetson
was the trigger, ENG-2158 - would otherwise reach by inheriting the shared
provider.

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
bakar build --on pc2 --yes --target cryptsetup-var meta-avocado/kas/machine/qemux86-64-nodeliv.yml
```

Run from `/home/tiamarin/repos/work/peridio`; dispatched to pc2, both nodes on
`bakar 0.29.2 (b2948127b778)`.

## Result: REFUSED

Exit 2, `kas_build: exit_code=2`, parsing halted, no image produced. The exact
message, from the run log at
`build-qemux86-64-nodeliv/build/runs/20260903-161900/kas.log`:

```
ERROR: .../meta-avocado/recipes-core/cryptsetup-var/cryptsetup-var.bb: machine
avocado-qemux86-64-nodeliv declares encrypted-var but supplies no var-key
provider of its own: the var-key.sh that resolves for this machine is the
placeholder that cannot actually derive a key. Add a machine- or
vendor-specific var-key.sh (or var-hwkey.sh) ahead of it on FILESPATH before
shipping encrypted-var here.
ERROR: Parsing halted due to errors, see error messages above
```

## Confirmation this is the NEW check

- **Attributed to the recipe**: the ERROR is prefixed with the path to
  `cryptsetup-var.bb`, where the anonymous python lives.
- **Names the machine**: `avocado-qemux86-64-nodeliv`, verbatim.
- **Names the feature**: `encrypted-var`.
- **The bbclass diagnostics are absent.** Grepping the run log for the three
  strings `avocado-security-capabilities.bbclass` emits - `requested security
  feature`, `declares no AVOCADO_SECURITY_CAPABILITIES`, `not present in its
  AVOCADO_SECURITY_CAPABILITIES` - returns **0** matches. The refusal cannot be
  attributed to the older declaration check.

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
