# Task 4.1: deliverability refusal, observed live

Confirms the scenario the whole change exists for: a machine that declares
`encrypted-var` but has no var-key provider of its own is REFUSED by
`cryptsetup-var.bb`'s new deliverability check (task 2.2), not silently built.

## Why Raspberry Pi could not be used

Raspberry Pi's `AVOCADO_SECURITY_CAPABILITIES` already reads `""`
(`avocado-raspberrypi.inc:21`). No existing machine in the tree satisfies
both "declares `encrypted-var`" AND "has no `var-key.sh` override" - the
four machines with a `FILESEXTRAPATHS:prepend:<machine>` override on
`cryptsetup-var.bb` (`avocado-imx93-frdm`, `avocado-imx8mp-evk` via the
`avocado-imx` family override, `avocado-qemuarm64`, `avocado-qemux86-64`,
`avocado-x86-64`) all supply their own provider, so none of them would
trigger this check. A construction was required instead.

## Construction

A scratch machine, `avocado-qemux86-64-scratch-deliverability`, was created
by copying `meta-avocado-qemu/conf/machine/avocado-qemux86-64.conf` byte-for-
byte in structure under a new machine name (so the qemu layer's
`FILESEXTRAPATHS:prepend:avocado-qemux86-64` override - keyed on the exact
machine name - does not match, and `cryptsetup-var.bb`'s `FILESPATH` lookup
falls through to the shared, sentinel-carrying
`meta-avocado/recipes-core/cryptsetup-var/files/var-key.sh`), keeping the
inherited `AVOCADO_SECURITY_CAPABILITIES = "encrypted-var tpm2"` declaration,
and adding one line: `DISTRO_FEATURES:append = " encrypted-var"` - the
condition `cryptsetup-var.bb`'s anonymous python actually gates on (real
machines no longer set this; `kas/feature/encrypted-var.yml` was removed by
commit `0f20494c`, and the bbclass itself now only warns on a leftover
token). A matching scratch kas machine file,
`kas/machine/qemux86-64-scratch-deliverability.yml`, pointed `machine:` at
it and reused `kas/base.yml` plus the same feature includes as
`kas/machine/qemux86-64.yml`.

Both files were temporary. They have been deleted; `git status --short` in
`meta-avocado/` is clean except for this test file. The sibling build
directory `build-qemux86-64-scratch-deliverability/` that `bakar` created
outside the git repo (a sibling of `meta-avocado/`, alongside the
pre-existing `build-imx93-frdm/`, `build-qemux86-64/`,
`build-raspberrypi5/` from earlier tasks) was also removed.

## Command

```
bakar bitbake cryptsetup-var kas/machine/qemux86-64-scratch-deliverability.yml
```

Run from `/home/tiamarin/repos/work/peridio/meta-avocado/`. This is a bare
recipe parse/build, not a full image build - the same pattern task 1.2 used
to confirm `bb.fatal` aborts rather than skips.

## Result

Exit code: `1`. `bakar` reported `bitbake cryptsetup-var failed (exit 1).`

The exact refusal message, unwrapped from bitbake's line-wrapped output:

```
ERROR: /home/tiamarin/repos/work/peridio/build-qemux86-64-scratch-deliverability/build/../../meta-avocado/meta-avocado/recipes-core/cryptsetup-var/cryptsetup-var.bb: machine avocado-qemux86-64-scratch-deliverability declares encrypted-var but supplies no var-key provider of its own: the var-key.sh that resolves for this machine is the placeholder that cannot actually derive a key. Add a machine- or vendor-specific var-key.sh (or var-hwkey.sh) ahead of it on FILESPATH before shipping encrypted-var here.
```

## Confirmation this is the NEW check, not the bbclass's

- **Names the machine**: `avocado-qemux86-64-scratch-deliverability`, present verbatim in the message.
- **Names `encrypted-var`**: present verbatim ("declares encrypted-var but supplies no var-key provider").
- **Distinct wording from `avocado-security-capabilities.bbclass`'s two diagnostics**:
  - Absent-declaration: `"machine %s requested security feature(s) %s but declares no AVOCADO_SECURITY_CAPABILITIES at all. Unmet prerequisite: add AVOCADO_SECURITY_CAPABILITIES..."` - not present in the run's output at all (this machine's declaration is non-empty, so that branch cannot fire).
  - Feature-not-declared: `"machine %s requested security feature(s) %s not present in its AVOCADO_SECURITY_CAPABILITIES declaration..."` - also not present; `encrypted-var` is not even in `AVOCADO_SECURITY_FEATURES` (`ahab ftpm tpm2 verified-boot`), so the bbclass's `ConfigParsed` handler treats it as nothing-requested and returns without firing (confirmed by the bbclass source at `avocado-security-capabilities.bbclass:66-76`).
  - The message that DID fire is the recipe-level one added in task 2.2: it talks about a "var-key provider", "the placeholder that cannot actually derive a key", and "FILESPATH" - vocabulary that exists only in `cryptsetup-var.bb`'s anonymous python, not in the bbclass.
  - The run's log also shows the bbclass's separate, unrelated `bb.warn` ("DISTRO_FEATURES contains encrypted-var, which no longer selects anything... Drop the token") - this is a warning, not the fatal refusal, and confirms the two checks are visibly different code paths firing side by side in the same run: the bbclass only warns, the recipe check fatals.

## Build completed without success?

No. The run exited 1 and bitbake's parse halted on the `bb.fatal` above
("ERROR: Parsing halted due to errors, see error messages above"). The build
was REFUSED, not completed.
