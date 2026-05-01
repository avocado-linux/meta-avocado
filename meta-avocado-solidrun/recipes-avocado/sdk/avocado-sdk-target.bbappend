FILESEXTRAPATHS:prepend := "${THISDIR}/${PN}:"
FILESEXTRAPATHS:prepend := "${@':'.join(['%s/stone' % layer for layer in d.getVar('BBLAYERS').split()])}:"

# Stone bundle artifacts the rzv2n provisioning scripts ship to the host.
do_compile[depends] += "u-boot:do_deploy"
do_compile[depends] += "firmware-pack:do_deploy"
do_compile[depends] += "flash-writer:do_deploy"
do_compile[depends] += "extlinux-rzv2n-sr-som:do_deploy"

RDEPENDS:${PN}:append = " \
  nativesdk-rz-flash-writer-tool \
  nativesdk-android-tools \
  nativesdk-gptfdisk \
  nativesdk-mtools \
  nativesdk-dosfstools \
  nativesdk-util-linux-lsblk \
  nativesdk-util-linux-blockdev \
"
