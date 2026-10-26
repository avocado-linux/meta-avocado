DESCRIPTION = "Rockchip USB loader (DDR init + usbplug) for rkdeveloptool db"

# rkdeveloptool can only reach the eMMC from MaskROM after `db <loader>`
# brings up DDR and the rockusb storage gadget. idbloader.img is the boot
# image, not a loader; this packs rkbin's own one with boot_merger.
require recipes-bsp/rkbin/rockchip-rkbin.inc

RKBIN_LOADER_INI:rk3568 ?= "RKBOOT/RK3568MINIALL.ini"
RKBIN_LOADER_INI:rk3588s ?= "RKBOOT/RK3588MINIALL.ini"

# ponytail: boot_merger is rkbin's prebuilt x86-64 binary, so this recipe
# needs an x86-64 build host; port tools/boot_merger's packer if arm64
# builders need it.
do_deploy() {
	if [ -z "${RKBIN_LOADER_INI}" ]; then
		bbfatal "Non-empty RKBIN_LOADER_INI:<MACHINE> required!"
	fi
	cd ${S}
	out=$(sed -n 's/^PATH=//p' ${RKBIN_LOADER_INI})
	rm -f "$out"
	./tools/boot_merger ${RKBIN_LOADER_INI}
	install -D -m 644 "$out" ${DEPLOYDIR}/rockchip-usb-loader.bin
}
