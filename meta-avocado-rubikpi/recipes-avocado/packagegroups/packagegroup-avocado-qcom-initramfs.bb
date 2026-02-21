DESCRIPTION = "Packagegroup for qcom initramfs images"
LICENSE = "Apache-2.0"

PACKAGE_ARCH = "${MACHINE_ARCH}"
inherit packagegroup
PACKAGES = "${PN}"

RDEPENDS:${PN} = " \
    ${VIRTUAL-RUNTIME_dev_manager} \
    os-release-initrd \
    erofs-utils \
    squashfs-tools \
    e2fsprogs \
    e2fsprogs-e2fsck \
    e2fsprogs-mke2fs \
    e2fsprogs-resize2fs \
    e2fsprogs-tune2fs \
"

# Recommend kernel modules as they might be built-in
RRECOMMENDS:${PN} = " \
    kernel-module-phy-qcom-qmp \
    kernel-module-qcom-pon \
    kernel-module-qnoc-sm8250 \
    kernel-module-ufs-qcom \
"
