# Task 4.2: `avocado-imx93-frdm` is unaffected by the deliverability check

Confirms the negative case: a machine that supplies its own var-key provider
must not be touched by the new deliverability check (task 2.2) - the build
succeeds exactly as it did before this change, and the shipped `var-key.sh`
is still the nxp one, byte-identical to the pre-change file.

## Why `avocado-imx93-frdm`

`meta-avocado-nxp/conf/machine/avocado-imx93-frdm.conf:161` declares:

```
AVOCADO_SECURITY_CAPABILITIES = "encrypted-var verified-boot${@bb.utils.contains('MACHINE_FEATURES', 'optee-ftpm', ' ftpm tpm2', '', d)}"
```

so it requests `encrypted-var` unconditionally. `meta-avocado-nxp` also
carries its own provider: `cryptsetup-var.bbappend` sets
`FILESEXTRAPATHS:prepend:avocado-imx := "${THISDIR}/files:"`, which resolves
ahead of the shared, sentinel-carrying
`meta-avocado/recipes-core/cryptsetup-var/files/var-key.sh` for every
`avocado-imx*` machine, `avocado-imx93-frdm` included. This is the one
existing machine that both requests `encrypted-var` and has always shipped
with a real provider - the case the deliverability check must not fire on.

## The nxp `var-key.sh` was not touched by this change

```
$ git log --oneline -- meta-avocado-nxp/recipes-core/cryptsetup-var/files/var-key.sh
788d3cc4 nxp: build CAAM and its trusted-keys backend into every i.MX kernel; encrypted-var on imx8mp-evk
3bac5f09 imx93: derive the /var key from the SoC UID instead of an absent secret
ec9a55a3 cryptsetup-var: relocate recipe from meta-avocado-nxp to shared layer
a2f53673 cryptsetup-var: document phase-2 dispatch table in var-key.sh
1c796c0c meta-avocado-nxp: Add Argon2id-based /var LUKS key derivation script

$ git diff 42243a40..HEAD -- meta-avocado-nxp/recipes-core/cryptsetup-var/files/var-key.sh
(empty - no output)
```

`42243a40` is the commit immediately before this change's range
(`0ef408ff`..`9d28ca18`) began. No commit in that range touches the nxp
file. Only the shared file under
`meta-avocado/recipes-core/cryptsetup-var/files/var-key.sh` was marked with
the sentinel, by `0ef408ff`:

```
$ grep -n "unusable" meta-avocado-nxp/recipes-core/cryptsetup-var/files/var-key.sh
(no output)

$ grep -n "unusable" meta-avocado/recipes-core/cryptsetup-var/files/var-key.sh
15:# avocado-var-key-provider: unusable
```

## Command

```
bakar bitbake cryptsetup-var kas/machine/imx93-frdm.yml
```

Run from `/home/tiamarin/repos/work/peridio/meta-avocado/`. Same bare
recipe-build pattern used by tasks 1.2 and 4.1.

## Result: build succeeds, no refusal

Exit code: `0`.

```
INFO     ✓ parsing recipes complete (23s)  [3924 fresh, cache empty]
✓ parse (23s)  ──  ✓ setscene  ──  ✓ tasks (1s)   36s
 100% sstate (1122 cached, 0 will build)
kas_build ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 2741/2741 tasks
2 warnings, 0 errors
INFO     ✓ kas_shell_live
INFO     ✓ bitbake_events
```

No `bb.fatal`, no "declares encrypted-var but supplies no var-key provider"
message, no parse abort - the new check (task 2.2) did not fire, as
expected for a machine with its own provider.

## Result: shipped `var-key.sh` is the nxp one, byte-identical

Compared the recipe's unpacked source, the packaged output, and the file
installed into the initramfs image against the in-tree nxp file:

```
$ sha256sum build-imx93-frdm/build/tmp/work/cortexa55-avocado-linux/cryptsetup-var/1.0/sources/var-key.sh
40bbc2b970aa689e469b112e68dc042b29800249e846826d9d72a20a44f6411a

$ sha256sum build-imx93-frdm/build/tmp/work/avocado_imx93_frdm-avocado-linux/avocado-image-initramfs/0.0.0/rootfs/usr/libexec/cryptsetup-var/var-key.sh
40bbc2b970aa689e469b112e68dc042b29800249e846826d9d72a20a44f6411a

$ sha256sum meta-avocado-nxp/recipes-core/cryptsetup-var/files/var-key.sh
40bbc2b970aa689e469b112e68dc042b29800249e846826d9d72a20a44f6411a
```

All three hashes match: `40bbc2b970aa689e469b112e68dc042b29800249e846826d9d72a20a44f6411a`.
The resolved `FILESPATH` lookup for `avocado-imx93-frdm` picked the nxp
provider, not the shared sentinel-carrying file - confirmed by re-running
the sentinel grep against the unpacked source:

```
$ grep -n "unusable" build-imx93-frdm/build/tmp/work/cortexa55-avocado-linux/cryptsetup-var/1.0/sources/var-key.sh
(no output)
```

## Cleanup

The sibling build directory `build-imx93-frdm/` that `bakar` created outside
the git repo was removed after the comparison above. No kas machine file or
other scratch artifact was created for this task -
`kas/machine/imx93-frdm.yml` is a pre-existing, permanent part of the repo.
`git status --short` in `meta-avocado/` is clean except for this test file.
