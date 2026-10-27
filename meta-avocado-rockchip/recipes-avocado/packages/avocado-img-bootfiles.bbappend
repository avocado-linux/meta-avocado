# The bootloader is machine-specific, so its deploy edge belongs here, not in
# the base recipe (docs/migrations/scarthgap-to-wrynose.md #46). Without it
# do_collect_artifacts can run before a rebuilt u-boot redeploys, and the
# package ships the previous u-boot.itb / uboot.env.
do_compile[depends] += "virtual/bootloader:do_deploy"
do_compile[depends] += "${@bb.utils.contains('STONE_PROVISIONING', 'emmc', 'rockchip-rkbin-usb-loader:do_deploy', '', d)}"
