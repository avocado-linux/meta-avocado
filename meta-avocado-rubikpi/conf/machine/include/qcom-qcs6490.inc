DEFAULTTUNE = "armv8-2a-crypto"
require conf/machine/include/arm/arch-armv8-2a.inc

SOC_FAMILY = "qcm6490"
require conf/machine/include/qcom-base.inc

# Additional Kernel cmdline parameters for debug builds
DBG_CMDLINE = "${@oe.utils.conditional('DEBUG_BUILD','1','earlycon page_owner=on qcom_scm.download_mode=1 slub_debug=FZP,zs_handle,zspage;FZPU','',d)}"

KERNEL_CMDLINE_EXTRA ?= "pcie_pme=nomsi rcupdate.rcu_expedited=1 rcu_nocbs=0-7 kpti=off kasan=off kasan.stacktrace=off no-steal-acc ${DBG_CMDLINE} swiotlb=128 mitigations=auto net.ifnames=0"

MACHINE_ESSENTIAL_EXTRA_RRECOMMENDS += "kernel-modules \
    kernel-module-qca6490"

MACHINE_EXTRA_RDEPENDS += "packagegroup-firmware-qcm6490"
