FILESEXTRAPATHS:prepend := "${THISDIR}/${PN}:"

BBCLASSEXTEND:append = " nativesdk"

# Replace the static fw_env.config with a symlink to a runtime-generated
# config. The avocado-uboot-env service detects the boot device (SD vs eMMC)
# and writes the correct config to /run/avocado/fw_env.config on every boot.
# Users can override by placing their own config at /var/lib/avocado/fw_env.config.
do_install:append:class-target:bootvars-ubootenv() {
    install -d ${D}${sysconfdir}
    rm -f ${D}${sysconfdir}/fw_env.config
    ln -sf /run/avocado/fw_env.config ${D}${sysconfdir}/fw_env.config
}
