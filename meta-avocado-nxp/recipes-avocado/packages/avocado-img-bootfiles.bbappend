# imx-boot deploys its build inputs (DDR firmware, SPL, u-boot-nodtb, the
# U-Boot control DTB, bl31/tee, mkimage_fit_atf.sh) plus the host-side
# mkimage_imx8 binary into DEPLOY_DIR_IMAGE/imx-boot-tools/. The inputs are
# exactly what a project needs to re-assemble imx-boot after injecting its own
# FIT public key into that DTB (fdt_add_pubkey + nativesdk-imx-mkimage-tools),
# so ship the directory - but not the binary: it is a build-host executable
# with an RPATH into the build tree, which fails do_package_qa, and the SDK
# gets a proper one from nativesdk-imx-mkimage-tools instead.
do_install:append() {
    rm -f ${D}/imx-boot-tools/mkimage_imx8
}

# The collect task scrapes DEPLOY_DIR_IMAGE, so its signature must carry the
# recipes that put the bootloader there or a U-Boot change never invalidates
# this package: observed on imx8mp-evk, where u-boot-imx rebuilt with a new
# CONFIG_SYS_BOOTM_LEN and imx-boot redeployed, but avocado-img-bootfiles was
# restored from sstate carrying the previous imx-boot - so `avocado provision`
# kept flashing the old bootloader and the board stayed in its boot loop. The
# avocado-stone:do_deploy dependency above does not carry this edge (that task
# is nostamp). Same recipe set avocado-stone.bbappend depends on, for the same
# reason: virtual/bootloader, not a hardcoded u-boot-imx, so CompuLab and
# Variscite boards are covered too.
do_collect_artifacts[depends] += "virtual/bootloader:do_deploy imx-boot:do_deploy"
