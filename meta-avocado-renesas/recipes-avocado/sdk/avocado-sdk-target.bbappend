FILESEXTRAPATHS:prepend := "${THISDIR}/${PN}:"
FILESEXTRAPATHS:prepend := "${@':'.join(['%s/stone' % layer for layer in d.getVar('BBLAYERS').split()])}:"

# Stone bundle artifacts the Renesas provisioning scripts ship to the host.
do_compile[depends] += "u-boot:do_deploy"
do_compile[depends] += "firmware-pack:do_deploy"
do_compile[depends] += "flash-writer:do_deploy"
# Derived from MACHINE_SHORT_NAME, same as in avocado-stone.bbappend.
do_compile[depends] += "extlinux-${MACHINE_SHORT_NAME}:do_deploy"

RDEPENDS:${PN}:append = " \
  nativesdk-rz-flash-writer-tool \
  nativesdk-android-tools \
  nativesdk-gptfdisk \
  nativesdk-mtools \
  nativesdk-dosfstools \
  nativesdk-util-linux-lsblk \
  nativesdk-util-linux-blockdev \
"
