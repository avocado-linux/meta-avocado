KBRANCH ?= "v7.2/standard/base"

require recipes-kernel/linux/linux-yocto.inc

# tools/objtool's disassembly support (DISAS, gated on #include <bfd.h> in
# tools/objtool/include/objtool/arch.h) auto-detects via a link-only probe in
# tools/objtool/Makefile - it checks that -lopcodes/-lbfd link, never that
# bfd.h itself is present. binutils-native's runtime .so is already staged
# via the cross-toolchain dependency chain, so the probe passes and
# BUILD_DISAS gets enabled, but do_compile then fails on the missing header:
# "fatal error: bfd.h: No such file or directory". linux-yocto.inc's own
# DEPENDS carries no binutils-native, so nothing stages the header into this
# recipe's own native sysroot. The Intel kernel recipe carries no
# PREFERRED_VERSION_linux-yocto override (grep across meta-avocado-x86-64/
# meta-avocado finds none), so it tracks wrynose's distro-default 6.18 line,
# not this vendored 7.2 - add the dependency here, scoped to the recipe that
# needs it, rather than to the shared .inc every kernel recipe includes.
DEPENDS += "binutils-native"

# CVE exclusions
include recipes-kernel/linux/cve-exclusion.inc

# board specific branches
KBRANCH:qemuarm  ?= "v7.2/standard/arm-versatile-926ejs"
KBRANCH:qemuarm64 ?= "v7.2/standard/base"
KBRANCH:qemumips ?= "v7.2/standard/mti-malta"
KBRANCH:qemuppc  ?= "v7.2/standard/qemuppc"
KBRANCH:qemuriscv64  ?= "v7.2/standard/base"
KBRANCH:qemuriscv32  ?= "v7.2/standard/base"
KBRANCH:qemux86  ?= "v7.2/standard/base"
KBRANCH:qemux86-64 ?= "v7.2/standard/base"
KBRANCH:qemuloongarch64  ?= "v7.2/standard/base"
KBRANCH:qemumips64 ?= "v7.2/standard/mti-malta"

SRCREV_machine:qemuarm ?= "56c7106647e505ca1fb15fd433b0bc991024764c"
SRCREV_machine:qemuarm64 ?= "d8a1ec518ab72fadb60dbe9eed3775b68975defd"
SRCREV_machine:qemuloongarch64 ?= "d8a1ec518ab72fadb60dbe9eed3775b68975defd"
SRCREV_machine:qemumips ?= "ab0e33fefa2a3d0366b2b8deb7cfb3be2d8dc436"
SRCREV_machine:qemuppc ?= "d8a1ec518ab72fadb60dbe9eed3775b68975defd"
SRCREV_machine:qemuriscv64 ?= "d8a1ec518ab72fadb60dbe9eed3775b68975defd"
SRCREV_machine:qemuriscv32 ?= "d8a1ec518ab72fadb60dbe9eed3775b68975defd"
SRCREV_machine:qemux86 ?= "d8a1ec518ab72fadb60dbe9eed3775b68975defd"
SRCREV_machine:qemux86-64 ?= "d8a1ec518ab72fadb60dbe9eed3775b68975defd"
SRCREV_machine:qemumips64 ?= "ab0e33fefa2a3d0366b2b8deb7cfb3be2d8dc436"
SRCREV_machine ?= "d8a1ec518ab72fadb60dbe9eed3775b68975defd"
SRCREV_meta ?= "b5d69636e3e56aa6a5b8f987b4587e7a56c4782a"

# set your preferred provider of linux-yocto to 'linux-yocto-upstream', and you'll
# get the <version>/base branch, which is pure upstream -stable, and the same
# meta SRCREV as the linux-yocto-standard builds. Select your version using the
# normal PREFERRED_VERSION settings.
BBCLASSEXTEND = "devupstream:target"
SRCREV_machine:class-devupstream ?= "500df175a7f9e6bc1a9c328590ca5150f84f9ff0"
PN:class-devupstream = "linux-yocto-upstream"
KBRANCH:class-devupstream = "v7.2/base"

SRC_URI = "git://git.yoctoproject.org/linux-yocto.git;name=machine;branch=${KBRANCH};protocol=https \
           git://git.yoctoproject.org/yocto-kernel-cache;type=kmeta;name=meta;branch=yocto-7.2;destsuffix=${KMETA};protocol=https"

LIC_FILES_CHKSUM = "file://COPYING;md5=6bc538ed5bd9a7fc9398086aedcd7e46"
LINUX_VERSION ?= "7.2.6"

PV = "${LINUX_VERSION}+git"

KMETA = "kernel-meta"
KCONF_BSP_AUDIT_LEVEL = "1"

KERNEL_DEVICETREE:qemuarmv5 = "arm/versatile-pb.dtb"

COMPATIBLE_MACHINE = "^(qemuarm|qemuarmv5|qemuarm64|qemux86|qemuppc|qemuppc64|qemumips|qemumips64|qemux86-64|qemuriscv64|qemuriscv32|qemuloongarch64)$"

# Functionality flags
KERNEL_EXTRA_FEATURES ?= "features/netfilter/netfilter.scc"
KERNEL_FEATURES:append = " ${KERNEL_EXTRA_FEATURES}"
KERNEL_FEATURES:append:qemuall = " cfg/virtio.scc features/drm-bochs/drm-bochs.scc cfg/net/mdio.scc"
KERNEL_FEATURES:append:qemux86 = " cfg/sound.scc cfg/paravirt_kvm.scc"
KERNEL_FEATURES:append:qemux86-64 = " cfg/sound.scc cfg/paravirt_kvm.scc"
KERNEL_FEATURES:append = " ${@bb.utils.contains("TUNE_FEATURES", "mx32", " cfg/x32.scc", "", d)}"
KERNEL_FEATURES:append = " ${@bb.utils.contains("DISTRO_FEATURES", "ptest", " features/scsi/scsi-debug.scc features/nf_tables/nft_test.scc", "", d)}"
KERNEL_FEATURES:append = " ${@bb.utils.contains("DISTRO_FEATURES", "ptest", " features/gpio/mockup.scc features/gpio/sim.scc", "", d)}"
KERNEL_FEATURES:append = " ${@bb.utils.contains("KERNEL_DEBUG", "True", " features/reproducibility/reproducibility.scc features/debug/debug-btf.scc", "", d)}"
# libteam ptests from meta-oe needs it
KERNEL_FEATURES:append = " ${@bb.utils.contains("DISTRO_FEATURES", "ptest", " features/net/team/team.scc", "", d)}"
# openl2tp tests from meta-networking needs it
KERNEL_FEATURES:append = " ${@bb.utils.contains("DISTRO_FEATURES", "ptest", " cgl/cfg/net/l2tp.scc", "", d)}"
KERNEL_FEATURES:append:powerpc = " arch/powerpc/powerpc-debug.scc"
KERNEL_FEATURES:append:powerpc64 = " arch/powerpc/powerpc-debug.scc"
KERNEL_FEATURES:append:powerpc64le = " arch/powerpc/powerpc-debug.scc"
# Do not add debug info for riscv32, it fails during depmod
# ERROR: modpost: __ex_table+0x17a4 references non-executable section '.debug_loclists'
# Check again during next major version upgrade
KERNEL_FEATURES:remove:riscv32 = "features/debug/debug-kernel.scc"
INSANE_SKIP:kernel-vmlinux:qemuppc64 = "textrel"
