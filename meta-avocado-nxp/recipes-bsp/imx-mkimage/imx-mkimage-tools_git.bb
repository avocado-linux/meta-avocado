SUMMARY = "imx-boot packers (i.MX8M and i.MX9) and mkimage_fit_atf.sh for repacking imx-boot outside bitbake"
DESCRIPTION = "NXP's boot-image packers as SDK host tools: the i.MX8M one and the \
i.MX9 AHAB container one (imx-mkimage's top-level build). meta-freescale's \
imx-mkimage recipe is `inherit native` and cannot be BBCLASSEXTENDed, and its \
deployed copy in imx-boot-tools/ is a build-host binary with an RPATH into the \
build tree, so neither reaches the SDK. This recipe builds only what a project \
needs to re-assemble imx-boot after injecting its own FIT public key into the \
U-Boot control DTB (fdt_add_pubkey): mkimage_imx8 (one C file, zlib) and the \
mkimage_fit_atf.sh ITS generator. The DDR firmware, SPL, u-boot-nodtb, bl31 \
and DTB inputs arrive via avocado-img-bootfiles' imx-boot-tools/ directory."
SECTION = "bsp"
LICENSE = "GPL-2.0-only"
LIC_FILES_CHKSUM = "file://${COREBASE}/meta/files/common-licenses/GPL-2.0-only;md5=801f80980d171dd6425610833a22dbe6"

# Same source pin as meta-freescale's imx-mkimage_git.inc (lf-6.18.2_1.0.0) so
# the packer matches the soc.mak the distro's imx-boot was assembled with.
# Pinned here rather than `require`d: the inc's SRC_URI carries a soc.mak
# patch that lives in meta-freescale's own files/ dir, which this recipe's
# FILESPATH cannot see - and this recipe never uses soc.mak.
SRC_URI = "git://github.com/nxp-imx/imx-mkimage.git;protocol=https;branch=${SRCBRANCH}"
SRCBRANCH = "lf-6.18.2_1.0.0"
SRCREV = "c0debd7c0b4a125bd3ca66bc68f1915882b2bb62"
PV = "1.0+git"
DEPENDS = "zlib"

# soc.mak's own rule for $(MKIMG), minus -static (nativesdk links the SDK's
# libz) and with the toolchain from the environment rather than a bare gcc.
#
# The i.MX9 soc.mak calls a different program under the same name: the
# container packer imx-mkimage's top-level Makefile builds from src/. It is
# installed as mkimage_imx_container. Its Makefile stamps `git rev-parse
# --short=8 HEAD` into build_info.h, which `-commit` writes into every image;
# take it from the same SRCREV so a re-pack matches the distro's imx-boot.
do_compile() {
    ${CC} ${CFLAGS} ${LDFLAGS} -std=c99 -Wall ${S}/iMX8M/mkimage_imx8.c -o ${B}/mkimage_imx8 -lz
    printf '#define MKIMAGE_COMMIT 0x%s\n' "$(echo ${SRCREV} | cut -c1-8)" > ${B}/build_info.h
    ${CC} ${CFLAGS} ${LDFLAGS} -std=c99 -Wall -I${B} -I${S}/src \
        ${S}/src/imx8qxb0.c ${S}/src/mkimage_imx8.c -o ${B}/mkimage_imx_container -lz
}

do_install() {
    install -d ${D}${bindir}
    install -m 0755 ${B}/mkimage_imx8 ${D}${bindir}/mkimage_imx8
    install -m 0755 ${B}/mkimage_imx_container ${D}${bindir}/mkimage_imx_container
    install -m 0755 ${S}/iMX8M/mkimage_fit_atf.sh ${D}${bindir}/mkimage_fit_atf.sh
}

# No COMPATIBLE_MACHINE: nativesdk.bbclass empties MACHINEOVERRIDES, so it
# could never match. avocado-sdk-target (meta-avocado-nxp bbappend) scopes
# the pull to the machines avocado-img-bootfiles ships a re-key procedure for.
BBCLASSEXTEND = "nativesdk"
