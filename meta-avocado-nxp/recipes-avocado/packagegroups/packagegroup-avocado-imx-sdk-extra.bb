DESCRIPTION = "Packagegroup for extra packages in Avocado NXP i.MX SDKs"
LICENSE = "Apache-2.0"

inherit packagegroup nospdx

RDEPENDS:${PN} = " \
  nativesdk-uuu \
"

# mkimage_imx8 + mkimage_fit_atf.sh, so a project can re-pack imx-boot after
# injecting its own FIT public key into the U-Boot control DTB. i.MX8M only:
# the recipe builds the iMX8M packer, and i.MX9 boots an AHAB container that
# is assembled differently. MACHINE_ARCH so the :mx8m-generic-bsp override
# resolves per board (this packagegroup is otherwise noarch/shared).
PACKAGE_ARCH = "${MACHINE_ARCH}"
# nativesdk-lz4: soc.mak compresses tee.bin with lz4 before mkimage_fit_atf.sh
# folds it into u-boot.itb (mkimage's own dtc dependency comes with
# nativesdk-u-boot-tools-mkimage already).
RDEPENDS:${PN}:append:mx8m-generic-bsp = " nativesdk-imx-mkimage-tools nativesdk-lz4"
