# Task 4.2: `avocado-imx93-frdm` is unaffected by the deliverability check

Confirms the negative case: a machine that supplies its own var-key provider
must not be refused by the check added in `cryptsetup-var.bb`. The build
succeeds, and the check is proven to have actually run rather than returning
early.

## Why this had to be re-run

The first attempt at this task was void. At the time the check gated on
`bb.utils.contains("DISTRO_FEATURES", "encrypted-var", ...)`, and nothing in
this tree sets that token - `kas/feature/encrypted-var.yml` is deleted and
`avocado-security-capabilities.bbclass` warns when a leftover one appears. So
the imx93 build returned at the FIRST line of the anonymous python and never
reached provider resolution. It proved the same feature-off property as task
4.3, not what this task claims. Commit `e49c8670` re-gated the check on
`AVOCADO_SECURITY_CAPABILITIES`, which `avocado-imx93-frdm.conf:161` declares
natively, so the check now fires for this machine without any hand-added token.

A passing build alone is exactly the weak evidence that made the first attempt
void, so it is not the evidence recorded here.

## Command

```
bakar build --on pc2 --yes --target cryptsetup-var meta-avocado/kas/machine/imx93-frdm.yml
```

Run from `/home/tiamarin/repos/work/peridio` (the workspace root). Dispatched to
the pc2 builder; both nodes on `bakar 0.29.2 (b2948127b778)`.

## Result 1: the build is not refused

```
build succeeded in 38s
sstate: match 99% (wanted 362, local 361, missed 1)
```

Repeated after the control below was reverted: `build succeeded in 37s`. No
`bb.fatal`, no deliverability diagnostic, no parse abort.

## Result 2 (the arming proof): poisoning the nxp provider DOES refuse it

A successful build cannot distinguish "the check ran and passed" from "the
check returned at its gate". To separate them, the sentinel was temporarily
added to the **nxp** provider
(`meta-avocado-nxp/recipes-core/cryptsetup-var/files/var-key.sh`) and the same
command re-run:

```
ERROR: avocado-imx93-frdm declares encrypted-var but supplies no var-key provider of
ERROR: Parsing halted due to errors, see error messages above
ERROR    ✗ kas_build: exit_code=2
kas build failed (exit 2).
```

This establishes two things at once:

1. **The check is armed for `avocado-imx93-frdm`** - it reaches the sentinel
   comparison and aborts on it, so the clean build in Result 1 passes because
   the provider is good, not because the gate returned early.
2. **imx93 resolves to the nxp provider, not the shared one.** Editing the nxp
   file changed the build outcome; had `FILESPATH` resolved to the shared
   `meta-avocado/recipes-core/cryptsetup-var/files/var-key.sh`, poisoning the
   nxp copy would have had no effect at all. This is stronger evidence for the
   falsifier's "shipped var-key.sh is the shared provider" clause than a hash
   comparison, which only shows two files match without showing which one the
   build chose.

The two provider files are distinct, so the substitution is observable:

```
nxp source:    40bbc2b970aa689e469b112e68dc042b29800249e846826d9d72a20a44f6411a
shared source: 69eba4c640030495efdc40cc17668b94b537d14265c40c2bedb62f302e1d8433
```

## Cleanup

The temporary sentinel was reverted immediately after the control run:

```
$ git status --short
(clean)
$ git diff --quiet HEAD -- meta-avocado-nxp/recipes-core/cryptsetup-var/files/var-key.sh
nxp var-key.sh: IDENTICAL to HEAD
$ grep -c 'avocado-var-key-provider: unusable' meta-avocado-nxp/.../var-key.sh
0
```

The sentinel is present only in the shared provider (task 2.1's deliverable),
which is where it belongs.

## Note on hashing the deployed file

No hash of an unpacked/installed `var-key.sh` is recorded for this run: at 99%
sstate reuse `do_unpack` does not execute, so no unpacked source exists in the
work directory to hash. Result 2 covers the same question more directly by
showing which file the resolution actually depends on.
