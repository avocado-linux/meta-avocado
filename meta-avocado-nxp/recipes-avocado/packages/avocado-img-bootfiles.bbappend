# imx-boot deploys its build inputs and the host-side mkimage_imx8 binary into
# DEPLOY_DIR_IMAGE/imx-boot-tools/. Provisioning consumes the assembled imx-boot
# image named in the stone manifest, never that directory, and packaging a
# native binary fails do_package_qa with a bad-RPATH error into the build tree.
AVOCADO_IMG_BOOTFILES_SKIP_EXTRA += " imx-boot-tools"

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
