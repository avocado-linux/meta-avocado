FILESEXTRAPATHS:prepend := "${THISDIR}/${PN}:"

BBCLASSEXTEND:append = " nativesdk"

# Replace the static /etc/fw_env.config with a symlink to a runtime-generated
# config. The avocado-uboot-env service detects the boot device at every boot
# (SD vs eMMC, i.e. mmcblk1 vs mmcblk2 depending on how the target was
# provisioned -- e.g. the uuu-emmc profile boots from eMMC) and writes the
# correct config to /run/avocado/fw_env.config. Users can override by placing
# their own config at /var/lib/avocado/fw_env.config.
#
# This runs as a do_install postfunc, NOT a plain do_install:append, on purpose:
# meta-avocado-distro's libubootenv bbappend has a higher BBFILE_PRIORITY, so
# its do_install:append (which installs a static, single-device fw_env.config)
# concatenates *after* ours and would clobber the symlink. A postfunc always
# runs after the entire do_install body -- every :append from every layer, at
# any priority -- so the symlink deterministically wins. Without this, a target
# booted from a device other than the static file's hardcoded one fails with
# "Cannot initialize environment" from fw_printenv.
#
# do_symlink_fw_env is defined unconditionally (as a no-op) and specialised for
# class-target:bootvars-ubootenv so the postfunc can be registered for every
# variant without erroring on nativesdk / non-ubootenv machines, where it does
# nothing.
do_symlink_fw_env() {
    :
}
do_symlink_fw_env:class-target:bootvars-ubootenv() {
    install -d ${D}${sysconfdir}
    rm -f ${D}${sysconfdir}/fw_env.config
    ln -sf /run/avocado/fw_env.config ${D}${sysconfdir}/fw_env.config
}
do_install[postfuncs] += "do_symlink_fw_env"
