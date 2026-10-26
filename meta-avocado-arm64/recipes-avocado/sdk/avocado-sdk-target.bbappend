FILESEXTRAPATHS:prepend := "${THISDIR}/${PN}:"
FILESEXTRAPATHS:prepend := "${@':'.join(['%s/stone' % layer for layer in d.getVar('BBLAYERS').split()])}:"

# img/usb provisioning builds the FAT ESPs with mkfs.fat and mcopy, and the
# GPT with sgdisk.
RDEPENDS:${PN}:append = " \
  nativesdk-mtools \
  nativesdk-dosfstools \
  nativesdk-gptfdisk \
"
