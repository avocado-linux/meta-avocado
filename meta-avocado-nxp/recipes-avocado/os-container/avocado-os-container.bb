SUMMARY = "AHAB-signed OS container (kernel + initramfs + device tree) for i.MX9"
DESCRIPTION = "Packs the initramfs-bundled kernel Image and its device tree into \
an AHAB container and signs it with the OEM SRK, so U-Boot can extend the root of \
trust from the bootloader through to the initrd that unlocks /var."
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
    if not bb.utils.to_boolean(d.getVar('INITRAMFS_IMAGE_BUNDLE')):
        bb.fatal("INITRAMFS_IMAGE_BUNDLE is not set, so no initramfs-bundled "
                 "kernel is built and the container would carry a kernel with "
                 "no initrd. The AHAB boot flow passes booti no ramdisk "
                 "argument, so /var would never be unlocked. Set it in the "
                 "machine configuration.")
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
AVOCADO_DTB_LOAD_ADDR ?= "0x94000000"

# Where the environment stages the container before authenticating it. Recorded
# here only so the layout check below can see it - nothing in the container
# lands at this address, and nothing asserts the environment agrees. Keeping
# the two in step is manual, and a drift makes the check below validate an
# address the board does not use, so change cntr_addr and this together.
AVOCADO_CNTR_LOAD_ADDR ?= "0xa8000000"
AVOCADO_CNTR_SOC ?= "IMX9"
AVOCADO_CNTR_CORE ?= "a55"

# Set per machine; no default, since the wrong dtb builds a container that
# authenticates and then boots a kernel with the wrong hardware description.
AVOCADO_KERNEL_DTB ?= ""

# The initramfs-bundled kernel, not the bare Image beside it. Both are deployed
# when INITRAMFS_IMAGE_BUNDLE is set, and the bare one is the wrong choice here:
# it authenticates and boots, then finds no initrd to unlock /var from. The
# name is kernel-artifact-names.bbclass's INITRAMFS_LINK_NAME symlink, so it
# tracks the build without carrying a version or timestamp.
AVOCADO_KERNEL_IMAGE ?= "Image-initramfs-${MACHINE}.bin"

OS_CONTAINER = "os_cntr_signed.bin"

do_compile() {
    cd ${B}

    cp ${DEPLOY_DIR_IMAGE}/${AVOCADO_KERNEL_IMAGE} ${B}/Image
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

# The addresses were chosen when the kernel was ~33 MB. Bundling the initramfs
# made it ~170 MB, which put its unpack range over both the device tree and the
# container's own staging address - U-Boot stopped with "FDT image overlaps OS
# image", and had it not, authentication would have overwritten the container
# that container_get_image_dst() reads immediately afterwards.
#
# Checking that the addresses merely differ cannot catch that, so compare the
# ranges the payload actually occupies. Python rather than shell because
# bitbake's parser rejects $(( in a task body.
python avocado_os_container_check_layout() {
    import os

    image = os.path.join(d.getVar('B'), 'Image')
    if not os.path.exists(image):
        bb.fatal("no staged kernel to measure; the container was not built")

    size = os.path.getsize(image)
    kernel = int(d.getVar('AVOCADO_KERNEL_LOAD_ADDR'), 16)
    fdt = int(d.getVar('AVOCADO_DTB_LOAD_ADDR'), 16)
    cntr = int(d.getVar('AVOCADO_CNTR_LOAD_ADDR'), 16)
    end = kernel + size

    if end > fdt:
        bb.fatal("kernel occupies 0x%x-0x%x, which covers the device tree at "
                 "0x%x. Raise AVOCADO_DTB_LOAD_ADDR and fdt_addr together."
                 % (kernel, end, fdt))
    if end > cntr:
        bb.fatal("kernel occupies 0x%x-0x%x, which covers the container staged "
                 "at 0x%x. Authentication would overwrite the container while "
                 "unpacking it. Raise AVOCADO_CNTR_LOAD_ADDR and cntr_addr "
                 "together." % (kernel, end, cntr))
}
do_compile[postfuncs] += "avocado_os_container_check_layout"

do_deploy() {
    install -Dm 0644 ${B}/${OS_CONTAINER} ${DEPLOYDIR}/${OS_CONTAINER}
}

addtask deploy after do_compile before do_build
