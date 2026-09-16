DESCRIPTION = "Select which storage device UEFI boots from at runtime"
LICENSE = "Apache-2.0"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/Apache-2.0;md5=89aea4e17d99a7cacdbeed46a0096b10"

SRC_URI = "file://avocado-set-boot-device"

# Only file:// fetches — wrynose no longer auto-creates ${S}, so set
# it explicitly to UNPACKDIR (where bitbake places file:// files).
S = "${UNPACKDIR}"

# Architecture-independent shell. It lives in the common layer rather than in
# meta-avocado-nvidia because BootOrder is a UEFI concept, not a Tegra one -
# meta-avocado-x86-64 already ships efibootmgr for A/B slot activation and can
# consume this unchanged.
inherit allarch

# efibootmgr does the part that is genuinely hard in shell: decoding an EFI
# device path well enough to say which entry is the NVMe one. efivar comes with
# it and is what clears the immutable flag efivarfs puts on the variables.
RDEPENDS:${PN} = "efibootmgr efivar"

do_install() {
    install -d ${D}${sbindir}
    install -m 0755 ${UNPACKDIR}/avocado-set-boot-device ${D}${sbindir}/avocado-set-boot-device
}

FILES:${PN} += "${sbindir}/avocado-set-boot-device"
