FILESEXTRAPATHS:prepend := "${THISDIR}/${PN}:"
FILESEXTRAPATHS:prepend := "${THISDIR}/${PN}/env:"

SRC_URI:append:qemuarm64 = " \
  file://0001-qemu-arm-mmc-init.patch \
  file://avocado.cfg \
  file://env-mmc.cfg \
"

SRC_URI:append:qemux86-64 = " \
  file://x86-rom.cfg \
  file://avocado.cfg \
  file://env-mmc.cfg \
"

MKENVIMAGE_EXTRA_ARGS = "-r"

do_configure:prepend:qemuarm64() {
  cat ${UNPACKDIR}/avocado.cfg >> ${S}/configs/${UBOOT_MACHINE}
  cat ${UNPACKDIR}/env-mmc.cfg >> ${S}/configs/${UBOOT_MACHINE}
}

do_configure:prepend:qemux86-64() {
  cat ${UNPACKDIR}/x86-rom.cfg >> ${S}/configs/${UBOOT_MACHINE}
  cat ${UNPACKDIR}/avocado.cfg >> ${S}/configs/${UBOOT_MACHINE}
}

do_deploy:append:qemux86-64() {
  if [ -f "${B}/u-boot.rom" ]; then
      install -m 0644 ${B}/u-boot.rom ${DEPLOYDIR}/u-boot.rom
  fi
}
