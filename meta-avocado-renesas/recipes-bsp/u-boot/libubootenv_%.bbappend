# The rzv2n-sr-som fw_env.config: meta-avocado-distro's bbappend installs the
# first fw_env.config on FILESPATH as /etc/fw_env.config.
FILESEXTRAPATHS:prepend:rzv2n-sr-som := "${THISDIR}/libubootenv:"
