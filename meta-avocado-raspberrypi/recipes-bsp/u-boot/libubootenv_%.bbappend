FILESEXTRAPATHS:prepend := "${THISDIR}/${PN}:"

BBCLASSEXTEND:append = " nativesdk"

# Replace the static fw_env.config with a symlink to the runtime-generated
# config. The avocado-uboot-env service mounts the env FAT partition and
# writes the correct config to /run/avocado/fw_env.config on every boot.
#
# Run as a postfunc so this executes AFTER meta-avocado-distro's do_install
# append (which has a higher BBFILE_PRIORITY and would otherwise re-install
# the static file on top of our symlink). Varflags don't support overrides,
# so gate on the override set via anonymous python.
python __anonymous() {
    overrides = d.getVar('OVERRIDES').split(':')
    if 'bootvars-ubootenv' in overrides and 'class-target' in overrides:
        d.appendVarFlag('do_install', 'postfuncs', ' replace_fw_env_with_symlink')
}

replace_fw_env_with_symlink() {
    install -d ${D}${sysconfdir}
    rm -f ${D}${sysconfdir}/fw_env.config
    ln -sf /run/avocado/fw_env.config ${D}${sysconfdir}/fw_env.config
}
