SUMMARY = "AHAB-signed OS container (kernel + device tree) for i.MX9"
DESCRIPTION = "Packs the kernel Image and its device tree into an AHAB container \
and signs it with the OEM SRK, so U-Boot can extend the root of trust from the \
bootloader to Linux."
LICENSE = "MIT"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/MIT;md5=0835ade698e0bcf8506ecda2f7b4f302"

inherit avocado-ahab-sign deploy

# mkimage_imx8 is deployed by imx-boot into imx-boot-tools; the kernel and dtb
# come from the kernel's own deploy.
do_compile[depends] += " \
    imx-boot:do_deploy \
    virtual/kernel:do_deploy \
"

PACKAGE_ARCH = "${MACHINE_ARCH}"
COMPATIBLE_MACHINE = "(avocado-imx93-frdm|avocado-imx91-frdm)"

# Only meaningful with AHAB on: without it U-Boot boots a raw Image and this
# container has no consumer.
python () {
    if not bb.utils.contains('DISTRO_FEATURES', 'ahab', True, False, d):
        raise bb.parse.SkipRecipe("requires the 'ahab' DISTRO_FEATURE")
    if not d.getVar('AVOCADO_KERNEL_DTB'):
        bb.fatal("AVOCADO_KERNEL_DTB is unset. Set it in the machine "
                 "configuration to the device tree this machine boots; the "
                 "container records it by name and nothing downstream notices "
                 "a wrong one until the kernel has the wrong hardware.")
}

do_configure[noexec] = "1"
do_install[noexec] = "1"

BOOT_TOOLS = "imx-boot-tools"

# These MUST match image_addr and fdt_addr in the machine's U-Boot environment
# (meta-avocado-nxp/recipes-bsp/u-boot/u-boot-imx/env/avocado-<machine>.txt).
# The container records where each payload is to be placed, and U-Boot reads
# those destinations back out of it via container_get_image_dst() rather than
# from the environment - so a mismatch here does not fail the build, it boots a
# kernel to the wrong address.
AVOCADO_KERNEL_LOAD_ADDR ?= "0x80200000"
AVOCADO_DTB_LOAD_ADDR ?= "0x83000000"
AVOCADO_CNTR_SOC ?= "IMX9"
AVOCADO_CNTR_CORE ?= "a55"

# Set per machine; no default, since the wrong dtb builds a container that
# authenticates and then boots a kernel with the wrong hardware description.
AVOCADO_KERNEL_DTB ?= ""

OS_CONTAINER = "os_cntr_signed.bin"

do_compile() {
    cd ${B}

    cp ${DEPLOY_DIR_IMAGE}/Image ${B}/Image
    cp ${DEPLOY_DIR_IMAGE}/${AVOCADO_KERNEL_DTB} ${B}/${AVOCADO_KERNEL_DTB}

    ${DEPLOY_DIR_IMAGE}/${BOOT_TOOLS}/mkimage_imx8 \
        -soc ${AVOCADO_CNTR_SOC} \
        -c -ap ${B}/Image ${AVOCADO_CNTR_CORE} ${AVOCADO_KERNEL_LOAD_ADDR} \
        --data ${B}/${AVOCADO_KERNEL_DTB} ${AVOCADO_CNTR_CORE} ${AVOCADO_DTB_LOAD_ADDR} \
        -out ${B}/flash_os.bin

    if [ ! -f ${B}/flash_os.bin ]; then
        bbfatal "mkimage_imx8 produced no OS container"
    fi

    avocado_ahab_sign ${B}/flash_os.bin ${B}/${OS_CONTAINER}
}

do_deploy() {
    install -Dm 0644 ${B}/${OS_CONTAINER} ${DEPLOYDIR}/${OS_CONTAINER}
}

addtask deploy after do_compile before do_build
