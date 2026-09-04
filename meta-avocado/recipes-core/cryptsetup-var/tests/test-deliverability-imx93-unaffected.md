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
the pc2 builder; both nodes on `bakar 0.29.2 (cd4619e8eae7)`.

## Result 1: the build is not refused

```
bakar[build] phase=tasks sstate=99% tasks=2741/2741 running=0 elapsed=40s
build succeeded in 42s
```

No `bb.fatal`, no deliverability diagnostic, no parse abort, and no refusal from
the `do_install` execution tier.

## Result 2 (the arming proof): the execution tier leaves its fixtures on disk

A successful build cannot distinguish "the check ran and passed" from "the
check returned at its gate", so a passing build is not the evidence.

This section previously used a poison control: the `unusable` sentinel was
temporarily added to the nxp provider and the build re-run to watch it refuse.
That control no longer produces the refusal it quoted. Since `eb664479` the
parse tier requires EXACTLY ONE status line, and the nxp provider already
declares `usable`, so adding a second one now trips the duplicate-declaration
branch and reports "carries 2 status lines" rather than "declares itself
unusable". The old quotation was a message the current code cannot emit.

The second tier replaced the need for a poison control with direct evidence.
`do_install` builds two synthetic identity fixtures from the paths the resolved
provider declares, and those directories survive in `WORKDIR` after the run. If
the check had returned at its capability gate, no fixture would exist at all.
Read back from the pc2 builder after the run above:

```
var-key-deliverability-fixture-a
    sys/devices/soc0/serial_number             -> avocado-synthetic-identity-aaaa00000000000000000001
    sys/firmware/devicetree/base/serial-number -> avocado-synthetic-identity-aaaa00000000000000000001
var-key-deliverability-fixture-b
    sys/devices/soc0/serial_number             -> avocado-synthetic-identity-bbbb00000000000000000002
    sys/firmware/devicetree/base/serial-number -> avocado-synthetic-identity-bbbb00000000000000000002
```

This establishes three things:

1. **The check is armed for `avocado-imx93-frdm`.** Two fixtures exist, so the
   capability gate was passed and the provider was executed twice.
2. **imx93 resolves to the nxp provider, not the shared one.** The fixture
   contains exactly the two paths the nxp provider declares
   (`/sys/devices/soc0/serial_number` and the device-tree serial). The shared
   provider declares no identity paths at all, so had `FILESPATH` resolved to
   it the build would have been refused for a missing declaration rather than
   producing these directories.
3. **The build passed the differential.** Two different identities were written
   and the build did not refuse, so the provider returned two different 64-byte
   keys. A provider emitting a constant would have failed here.

## Cleanup

Nothing was poisoned for this run, so nothing needed reverting:

```
$ git status --short
(clean)
```

The `unusable` sentinel is present only in the shared provider (task 2.1's
deliverable), which is where it belongs.

## Note on hashing the deployed file

No hash of an unpacked/installed `var-key.sh` is recorded: at high sstate reuse
`do_unpack` does not execute, so no unpacked source exists to hash. Result 2
answers the same question more directly, by showing which provider's declared
paths the check actually built its fixture from.
