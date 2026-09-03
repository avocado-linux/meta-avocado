# Secure-partition support in the NXP OP-TEE fork on avocado-imx93-frdm

Task 5.2 of `var-key-provider-deliverability-check`. Confirms (or refutes) design
assumption A7: that the OP-TEE already in this board's BL32 can load a secure
partition, and that `CFG_RPMB_FS` can be turned on for `plat-imx`/`mx93`.

Investigation is source- and configuration-level only. No build was run - another
task holds the build tree.

## What is actually on the board

- Recipe: `meta-imx/meta-imx-bsp/dynamic-layers/meta-arm/recipes-security/optee/optee-os_4.10.0.imx.bb`
  - `SRCBRANCH = "lf-6.18.20_2.0.0"`, `SRCREV = "37c7fbf84c40eb9e5828532972ffb133b4917390"`
    (line 3-4). Upstream of the recipe is `git://github.com/nxp-imx/imx-optee-os.git`
    (`optee-os-common-imx.inc:11`).
- Platform mapping: `OPTEEMACHINE:mx93-nxp-bsp = "imx-mx93evk"` -> `PLATFORM=imx`,
  `PLATFORM_FLAVOR=mx93evk` (`optee-os-common-imx.inc:29`, `:35`).
- The board's own resolved build configuration is still on disk at
  `build-imx93-frdm/build/tmp/work/avocado_imx93_frdm-avocado-linux/optee-os/4.10.0.imx/build/conf.mk`
  even though `AVOCADO_RM_WORK=1` reaped the sources. Its header confirms
  `PLATFORM=imx` (line 4) / `PLATFORM_FLAVOR=mx93evk` (line 5), so every "as
  built today" value below is this board's, not a guess.

Source claims are checked against a read-only clone of the fork at that exact
SRCREV (`git describe` -> tag `lf-6.18.20-2.0.0`), under
`/var/tmp/claude-code/peridio/2026-09-03-stmm-optee-fork/imx-optee-os`.

## Verdict

**A7 holds.** The fork ships secure-partition support, and it is reachable for
`mx93`. Two independent SP mechanisms exist, and they are not the same thing -
the distinction decides which of the two follows from this note.

| Mechanism | Symbol | State on this board today | Reachable for mx93 |
|---|---|---|---|
| EDK2 StandaloneMM SP (`StandaloneMmPkg`) | `CFG_WITH_STMM_SP` | `n` | Yes, and already wired by NXP |
| FF-A secure partition (what trusted-services `smm-gateway` needs) | `CFG_SECURE_PARTITION` | `n` | Not blocked by the fork, but never exercised on i.MX |
| RPMB-backed secure storage | `CFG_RPMB_FS` | `n` | Yes, and already wired by NXP |

### 1. StandaloneMM SP: supported and pre-wired by NXP

- `core/arch/arm/kernel/stmm_sp.c` exists in the fork and is built by
  `core/arch/arm/kernel/sub.mk:44` (`srcs-$(CFG_WITH_STMM_SP) += stmm_sp.c`).
- `mk/config.mk:905-909` forces `CFG_WITH_STMM_SP=y` (and `CFG_EFILIB=y`) whenever
  `CFG_STMM_PATH` is non-empty; `core/sub.mk:83-87` then embeds the SP image via
  `scripts/gen_stmm_hex.py`.
- `core/arch/arm/plat-imx/conf.mk` contains **no** `force` of `CFG_WITH_STMM_SP`,
  `CFG_SECURE_PARTITION`, `CFG_STMM_PATH` or `CFG_RPMB_FS` in the `mx93` branch
  (`conf.mk:273-291`) or anywhere else in the file. The only architectures that
  force these off are RISC-V (`core/arch/riscv/riscv.mk:97`, `:103`).
- meta-imx already ships the integration:
  `meta-imx/meta-imx-bsp/dynamic-layers/meta-arm/recipes-security/stmm-imx/optee-os_%.imx.bbappend`
  sets `CFG_STMM_PATH=.../BL32_AP_MM.fd`, `CFG_RPMB_FS=y`, `CFG_REE_FS=n`,
  `CFG_RPMB_WRITE_KEY=y`, `CFG_RPMB_FS_DEV_ID=${RPMB_FS_DEV_ID}` (lines 10-23),
  gated on `MACHINE_FEATURES` containing `stmm` (line 26), with an
  mx93-specific device id: `RPMB_FS_DEV_ID:mx93-nxp-bsp = "0"` (line 7).
- The SP producer is present in this tree too:
  `stmm-imx/stmm-imx_git.bb` requires `recipes-bsp/uefi/edk2-firmware_202602.bb`,
  which exists at `meta-arm/meta-arm/recipes-bsp/uefi/edk2-firmware_202602.bb`,
  and declares `COMPATIBLE_MACHINE:imx-nxp-bsp = "(mx8-nxp-bsp|mx9-nxp-bsp)"` -
  i.MX93 is `mx9`.

Nothing in meta-avocado enables it: a search of `meta-avocado*` for `stmm` returns
no hit, so `MACHINE_FEATURES` for `avocado-imx93-frdm` does not carry `stmm` and
the bbappend above is inert today. That is a wiring gap on our side, not a fork gap.

### 2. FF-A secure partition: not blocked, but unproven on i.MX

This is the path task 5.1's trusted-services `smm-gateway` SP would take.

- Sources are present: `core/arch/arm/kernel/secure_partition.c`,
  `core/arch/arm/kernel/spmc_sp_handler.c` (both built by
  `core/arch/arm/kernel/sub.mk:45-46`) and `core/arch/arm/mm/sub.mk:9`
  (`srcs-$(CFG_SECURE_PARTITION) += sp_mem.c`).
- `CFG_SECURE_PARTITION ?= n` at `mk/config.mk:436` - a plain default, overridable
  from the recipe's `EXTRA_OEMAKE`, not a `force`. `mk/config.mk:433-437` also
  enables it implicitly when `SP_PATHS` is set.
- It needs an SPMC configuration. `core/arch/arm/arm.mk:109-113`: `CFG_CORE_SEL1_SPMC=y`
  forces `CFG_CORE_FFA=y`. `arm.mk:133-139`: `CFG_CORE_FFA` requires `CFG_DT=y` and
  `CFG_ARM64_core=y`; `arm.mk:151-153`: it is incompatible with `CFG_WITH_PAGER`.
  All three preconditions already hold in this board's build - `CFG_DT=y`
  (build `conf.mk:145`), `CFG_ARM64_core=y` (`:7`), `CFG_WITH_PAGER=n` (`:326`).
- **Caveat, and it is the load-bearing one.** No i.MX platform in the fork enables
  an SPMC: grep for `CFG_CORE_SEL1_SPMC` and `CFG_CORE_FFA` across
  `core/arch/arm/plat-imx/` returns nothing, and the only platform that forces
  `CFG_SECURE_PARTITION=y` is `core/arch/arm/plat-corstone1000/conf.mk:14`. So this
  path is reachable in the build system but has no i.MX precedent in the fork, and
  it also implies an FF-A-capable TF-A/BL31 on the NXP side, which this note did
  not examine.

`CFG_SPMC_TESTS` is a plain `?= n` at `mk/config.mk:1172` with no platform gate.
It only adds FF-A SPMC tests to xtest and is not needed by an SP at runtime.

### 3. `CFG_RPMB_FS`: reachable

- As built today it is off: `CFG_RPMB_FS=n` at build `conf.mk:236`, with
  `CFG_REE_FS=y` (`:224`) - i.e. secure storage currently lives in REE-FS. This
  matches what `optee-ftpm-init.bb` records and is consistent with design
  assumption A8.
- Nothing forces it: `core/arch/arm/plat-imx/conf.mk` has no `RPMB` occurrence at
  all, so the generic default applies and the recipe can set it.
- NXP itself sets it for this SoC family - `CFG_RPMB_FS=y` plus
  `RPMB_FS_DEV_ID:mx93-nxp-bsp = "0"` in the `stmm-imx` bbappend cited above - which
  is direct evidence that the vendor considers `CFG_RPMB_FS` supported on mx93,
  not merely syntactically settable.

## Consequences for the change

- The stop-and-report branch in task 5.2 does **not** fire. There is no vendor-fork
  gap; evaluating upstream OP-TEE is not required.
- The cheapest path on this board is NXP's own: `MACHINE_FEATURES += "stmm"` plus
  the `stmm-imx`/`edk2-firmware` recipes already in tree. That is the EDK2
  `StandaloneMmPkg` fallback named in A6's mitigation column, and here it is the
  *pre-integrated* option rather than the fallback.
- Choosing the trusted-services `smm-gateway` SP instead means being the first to
  run an FF-A SPMC on plat-imx in this fork. Nothing in the fork blocks it; nothing
  in the fork demonstrates it either. That gap should be priced into A6/A7 before
  5.1's platform survey picks a `TS_PLATFORM`.
- A8 is untouched by this note: turning `CFG_RPMB_FS=y` via the meta-imx bbappend
  also sets `CFG_REE_FS=n`, which would move the fTPM's NV storage off REE-FS as a
  side effect. That is exactly the coupling A8 warns about and still needs its own
  check.

## Not established here

- Whether the mx93 TF-A/BL31 in this build exposes an FF-A SPMD interface.
- Whether an SP actually loads at boot on this board - that needs a build and a
  boot log carrying the SP UUID, which A7's own evidence column asks for and which
  this task's no-build constraint excludes.
