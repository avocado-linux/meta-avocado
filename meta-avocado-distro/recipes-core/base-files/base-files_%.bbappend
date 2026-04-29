FILESEXTRAPATHS:prepend := "${THISDIR}/files:"

SRC_URI:append = " file://fstab"

# Default value for the var partition device
AVOCADO_VAR_PART_DEV ?= "PARTUUID=4d21b016-b534-45c2-a9fb-5c16e091fd2d"

do_install:append() {
    install -m 0644 ${UNPACKDIR}/fstab ${D}${sysconfdir}/fstab
    if [ "${AVOCADO_VAR_PART_DEV}" = "none" ]; then
        # Var partition is mounted dynamically by init (e.g. avocado-tegra-init)
        sed -i '/@AVOCADO_VAR_PART_DEV@/d' ${D}${sysconfdir}/fstab
    else
        sed -i 's|@AVOCADO_VAR_PART_DEV@|${AVOCADO_VAR_PART_DEV}|g' ${D}${sysconfdir}/fstab
    fi
}
