FILESEXTRAPATHS:prepend := "${THISDIR}/${PN}:"
FILESEXTRAPATHS:prepend := "${@':'.join(['%s/stone' % layer for layer in d.getVar('BBLAYERS').split()])}:"

# Stone bundle artifacts the stm32mp25-dk provisioning scripts consume.
do_compile[depends] += "u-boot-stm32mp:do_deploy"
do_compile[depends] += "tf-a-stm32mp:do_deploy"
do_compile[depends] += "optee-os-stm32mp:do_deploy"
do_compile[depends] += "extlinux-stm32mp25-dk:do_deploy"

RDEPENDS:${PN}:append = " \
  nativesdk-mtools \
  nativesdk-dosfstools \
  nativesdk-gptfdisk \
  nativesdk-util-linux-lsblk \
  nativesdk-util-linux-blockdev \
  nativesdk-dfu-util \
"
