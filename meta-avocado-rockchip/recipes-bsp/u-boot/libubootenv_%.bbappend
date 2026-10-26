FILESEXTRAPATHS:prepend := "${THISDIR}/${PN}:"

# /etc/fw_env.config -> /run/avocado/fw_env.config, written at boot by
# avocado-uboot-env for the disk the system booted from (SD or eMMC). A
# postfunc, so it runs after meta-avocado-distro's do_install:append installs
# the static default; same as meta-avocado-nxp's bbappend.
do_symlink_fw_env() {
    :
}
do_symlink_fw_env:class-target:bootvars-ubootenv() {
    install -d ${D}${sysconfdir}
    rm -f ${D}${sysconfdir}/fw_env.config
    ln -sf /run/avocado/fw_env.config ${D}${sysconfdir}/fw_env.config
}
do_install[postfuncs] += "do_symlink_fw_env"
