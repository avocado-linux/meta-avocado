# imx-boot deploys its build inputs and the host-side mkimage_imx8 binary into
# DEPLOY_DIR_IMAGE/imx-boot-tools/. Provisioning consumes the assembled imx-boot
# image named in the stone manifest, never that directory, and packaging a
# native binary fails do_package_qa with a bad-RPATH error into the build tree.
AVOCADO_IMG_BOOTFILES_SKIP_EXTRA += " imx-boot-tools"
