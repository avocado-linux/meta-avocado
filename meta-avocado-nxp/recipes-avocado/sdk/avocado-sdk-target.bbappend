FILESEXTRAPATHS:prepend := "${THISDIR}/${PN}:"
FILESEXTRAPATHS:prepend := "${@':'.join(['%s/stone' % layer for layer in d.getVar('BBLAYERS').split()])}:"

RDEPENDS:${PN}:append = " \
  nativesdk-fwup \
  nativesdk-libubootenv-bin \
  nativesdk-mkfat \
  nativesdk-uuu \
"

# The imx-boot packers rekey-imx-boot.sh calls (from avocado-img-bootfiles'
# imx-boot-tools/), which `avocado build` runs whenever a runtime sets
# signing.fit_key: in every SDK of the machines that ship the procedure, so a
# project never has to know to ask for them. lz4: soc.mak compresses tee.bin
# when it packs the i.MX8M U-Boot FIT.
RDEPENDS:${PN}:append:mx8m-generic-bsp = " nativesdk-imx-mkimage-tools nativesdk-lz4"
RDEPENDS:${PN}:append:mx91-generic-bsp = " nativesdk-imx-mkimage-tools"
RDEPENDS:${PN}:append:mx93-generic-bsp = " nativesdk-imx-mkimage-tools"
