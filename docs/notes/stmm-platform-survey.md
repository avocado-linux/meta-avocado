# StandaloneMM / trusted-services platform survey for i.MX93

Task 5.1 of the `var-key-provider-deliverability-check` change. Investigation
only - no build was run.

## Question

Can `ts-sp-smm-gateway` (the trusted-services StMM secure partition, which is
the candidate UEFI-variable store behind a `/var` key provider) be built for a
real i.MX93 target at all? That is assumption A6, the central bet of the second
half of this change.

## What was inspected

| Artifact | Path | Ref |
|---|---|---|
| Recipe | `meta-arm/recipes-security/trusted-services/ts-sp-smm-gateway_git.bb` | worktree at `/home/tiamarin/repos/work/peridio/meta-arm` |
| Recipe base | `meta-arm/recipes-security/trusted-services/trusted-services.inc` | same |
| Source pin | `meta-arm/recipes-security/trusted-services/trusted-services-src.inc` | `SRCREV_trusted-services = a5db25bc3f2892781a07620af5d6625900988281` |
| Upstream source | `https://git.trustedfirmware.org/TS/trusted-services.git` | tag `v1.3.0` = `a5db25bc` (read-only clone under `/var/tmp/claude-code/peridio/`) |

The source was not present in `DL_DIR` or any build tree, so it was cloned
read-only outside the repo and checked out at the exact `SRCREV` the recipe
pins. The enumeration below is from that tree, not from recipe names.

## TS_PLATFORM values the source actually ships

`TS_PLATFORM` is a path under `platform/providers/`. Every directory in the
pinned tree carrying a `platform.cmake` - the complete set at `v1.3.0`:

| `TS_PLATFORM` | Kind |
|---|---|
| `arm/automotive-rd/rd1ae` | Arm reference design (automotive), silicon-specific |
| `arm/automotive-rd/rdaspen` | Arm reference design (automotive), silicon-specific |
| `arm/corstone1000` | Arm Corstone-1000 (FVP and MPS3 FPGA) |
| `arm/fvp/fvp_base_revc-2xaemv8a` | Arm Fixed Virtual Platform (simulator) |
| `arm/n1sdp` | Arm Neoverse N1 SDP board |
| `arm/total_compute` | Arm Total Compute reference design |
| `ts/mock` | Mock drivers. `platform.cmake` header: "This should never be used for a production build" |
| `ts/vanilla` | Null provider. `platform.cmake` header: "doesn't provide any hardware backed services"; it `FATAL_ERROR`s if the deployment declares any platform driver dependency |

There are **eight** values and that is the whole set. There is no NXP entry, no
i.MX entry of any kind, and no generic Armv8-A entry. The six real-hardware
entries are all Arm Ltd. reference designs; none is a vendor SoC platform.

The `meta-arm` side matches: the only `TS_PLATFORM` assignments in the layer are
`arm/corstone1000` (`meta-arm-bsp/conf/machine/include/corstone1000.inc:23`)
and `arm/fvp/fvp_base_revc-2xaemv8a` for `fvp-base`
(`meta-arm-bsp/recipes-security/trusted-services/ts-arm-platforms.inc:13`). The
recipe default is `TS_PLATFORM ?= "ts/mock"`
(`trusted-services.inc:20`), and `COMPATIBLE_MACHINE ?= "invalid"` with only
`qemuarm64-secureboot` whitelisted (`trusted-services.inc:9-10`).

`meta-avocado` contains no trusted-services or FF-A SPMC wiring at all: a grep
for `SPMC`, `CFG_CORE_SEL1_SPMC`, `ts-sp-` and `trusted-services` across every
`.bb`/`.bbappend`/`.inc`/`.conf` in the layer returns nothing.

## Verdict

**No shipped `TS_PLATFORM` value serves i.MX93.** A6 does not hold as written.

The two entries that might look like escape hatches are not:

- `ts/mock` is explicitly disqualified by its own header comment. Its only
  mapping is `trng -> mock_trng.c`. Building StMM against it would produce a
  secure partition backed by mock drivers - a UEFI variable store that stores
  nothing durable. That is the exact failure mode this survey exists to rule
  out, and it is not a usable answer for real hardware.
- `ts/vanilla` is a null platform, not a hardware platform. It compiles only
  when the deployment declares zero `TS_PLATFORM_DRIVER_DEPENDENCIES`, and
  `smm-gateway` happens to declare none directly - so `ts/vanilla` may well
  *compile*. It still supplies none of the board-specific values a real target
  needs. `MM_COMM_BUFFER_ADDRESS` / `MM_COMM_BUFFER_PAGE_COUNT` (the shared MM
  communicate buffer that must match what TF-A and the UEFI payload agree on)
  are set per-platform - `arm/corstone1000/platform.cmake:32-33` sets them, and
  `meta-arm`'s `ts-sp-smm-gateway_%.bbappend` overrides them for
  `qemuarm64-secureboot` and for nothing else. A vanilla build would silently
  inherit the FVP-derived defaults from
  `deployments/smm-gateway/config/default-sp/CMakeLists.txt:65`
  (`0x00000008 0x81000000`), which is not an i.MX93 address. Compiling is not
  the same as working, and `ts/vanilla` clears only the first bar.

Making StMM real on i.MX93 would require, at minimum: authoring a new
`platform/providers/` entry upstream or as an out-of-tree platform, correct
`MM_COMM_BUFFER_*` values reserved in the i.MX93 memory map, an OP-TEE built as
an FF-A S-EL1 SPMC with the SP embedded, a backing secure-storage SP with a
non-mock backend, and a `COMPATIBLE_MACHINE` widening in `meta-arm`. None of
that exists today.

## Recommendation

STOP the StMM line of this change. Per the task's own instruction, the fallback
is EDK2 `StandaloneMmPkg`, which is a different and much larger change and
should be scoped separately rather than folded in here.

## Confidence and limits

The platform enumeration is high-confidence: it is a directory listing of the
exact pinned `SRCREV`, not an inference from recipe names. The claim that
`ts/vanilla` would compile for `smm-gateway` is *not* verified by a build - no
bitbake was run, per the task constraint - and is inferred from the absence of
`TS_PLATFORM_DRIVER_DEPENDENCIES` declarations reachable from the smm-gateway
deployment. The verdict does not rest on that inference: it rests on the
absence of any i.MX platform provider, which is directly observed.
