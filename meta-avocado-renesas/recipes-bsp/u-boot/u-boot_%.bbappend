FILESEXTRAPATHS:prepend := "${THISDIR}/${PN}:"

SRC_URI:append = " \
  file://avocado.cfg \
  file://env-nowhere.cfg \
  file://fastboot.cfg \
"

# The RDK has no USB device/gadget port (USB3.2 are host-only, the Micro-B is a
# UART), so u-boot fastboot cannot run here. Drop the shared fastboot fragment on
# this machine: it is dead weight that also pushed u-boot-nodtb.bin past the
# board's 0x100000 size limit. (env-nowhere.cfg keeps a harmless `fastboot`
# fallback token in BOOTCOMMAND, but the board config header overrides
# BOOTCOMMAND anyway, so nothing references the removed command at runtime.)
SRC_URI:remove:rzv2h-rdk = "file://fastboot.cfg"
