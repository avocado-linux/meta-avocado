FILESEXTRAPATHS:prepend := "${THISDIR}/files:"

SRC_URI:append = " \
  file://avocado-core.cfg \
  file://avocado-extra.cfg \
"

SRC_URI:append:reterminal = " file://reterminal.cfg"
SRC_URI:append:reterminal-dm = " file://reterminal.cfg"

# USB 3.0 xHCI PCI for FR202 (Renesas controller behind PCIe for SATA SSD)
SRC_URI:append:fr202 = " file://fr202-usb3.cfg"
