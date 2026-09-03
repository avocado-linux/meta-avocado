# Task 4.3: the check stays off when the capability is not declared

Confirms the third case: a machine that does not declare `encrypted-var` is
unaffected by the deliverability check existing, regardless of which var-key
provider it would resolve.

## Re-recorded after the gate changed

An earlier version of this record described the check as gating on
`DISTRO_FEATURES` and quoted `cryptsetup-var.bb:26` reading it. That line no
longer exists: commit `e49c8670` re-gated the check on
`AVOCADO_SECURITY_CAPABILITIES`, because `encrypted-var` is a retired
`DISTRO_FEATURES` token that no machine sets and that
`avocado-security-capabilities.bbclass` actively warns about. The old record
therefore attributed a real result to a mechanism that had been removed. It is
re-run and re-recorded here rather than edited, so the evidence matches the
code.

## Why `avocado-raspberrypi5`

The machine has to make the negative meaningful. Raspberry Pi does, on both
counts:

- **It declares nothing.** `avocado-raspberrypi.inc:27` sets
  `AVOCADO_SECURITY_CAPABILITIES = ""`, so the check's first gate returns
  early.
- **It has no var-key provider.** No `cryptsetup-var.bbappend` or
  `FILESEXTRAPATHS:prepend` exists anywhere under `meta-avocado-raspberrypi`,
  so `FILESPATH` falls through to the shared, sentinel-carrying
  `meta-avocado/recipes-core/cryptsetup-var/files/var-key.sh` - the same
  resolution task 4.1's scratch machine gets.

That second point is what stops this being a trivial pass. If the declaration
were not empty, the sentinel gate WOULD fire for this machine. So the only
thing suppressing the refusal here is the absent declaration, which is exactly
the property under test - not the presence of a working provider, which is what
task 4.2 covers.

## Command

```
bakar build --on pc2 --yes --target cryptsetup-var meta-avocado/kas/machine/raspberrypi5.yml
```

Run from `/home/tiamarin/repos/work/peridio`; dispatched to pc2, both nodes on
the same bakar content identity.

## Result: unaffected

```
build succeeded in 1m23s
remote run-id: 20260903-165000
```

Exit 0. No `bb.fatal`, no deliverability diagnostic, no parse abort. The check
returned at its first gate without resolving a provider.

## The three cases together

| Task | Machine | Declares `encrypted-var` | Provider | Outcome |
|---|---|---|---|---|
| 4.1 | scratch (`avocado-qemux86-64-nodeliv`) | yes | none (falls to shared sentinel) | **REFUSED** |
| 4.2 | `avocado-imx93-frdm` | yes | own (nxp) | builds; refuses when the nxp provider is poisoned |
| 4.3 | `avocado-raspberrypi5` | no | none (falls to shared sentinel) | builds |

4.1 and 4.3 differ in exactly one variable - the declaration - and resolve to
the same provider, which is what isolates the first gate. 4.2 and 4.1 differ in
exactly one variable - the provider - and both declare, which is what isolates
the second.
