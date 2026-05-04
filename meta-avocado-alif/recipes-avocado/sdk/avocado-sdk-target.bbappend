FILESEXTRAPATHS:prepend := "${THISDIR}/${PN}:"
FILESEXTRAPATHS:prepend := "${@':'.join(['%s/stone' % layer for layer in d.getVar('BBLAYERS').split()])}:"

# Stone bundle artifacts the alif-e8-devkit provisioning scripts consume.
do_compile[depends] += "trusted-firmware-a:do_deploy"
do_compile[depends] += "linux-alif:do_deploy"

RDEPENDS:${PN}:append:devkit-e8 = " \
  nativesdk-alif-flash \
  nativesdk-mtools \
  nativesdk-dosfstools \
  nativesdk-gptfdisk \
  nativesdk-util-linux-lsblk \
  nativesdk-util-linux-blockdev \
"
