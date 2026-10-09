FILESEXTRAPATHS:prepend := "${THISDIR}/files:"

SRC_URI:append = " \
  file://avocado-core.cfg \
  file://avocado-extra.cfg \
"

SRC_URI:append:reterminal = " file://reterminal.cfg"
SRC_URI:append:reterminal-dm = " file://reterminal.cfg"

inherit avocado-kernel-feed
inherit avocado-kernel-builtin-provides
require recipes-kernel/linux/avocado-kernel-modules-packagegroup.inc

# Cellular modems on USB (Quectel EG25 and RG255 over QMI/MBIM/option, Telit
# over option/cdc_acm/cdc_ncm, Sierra-based parts over sierra/sierra_net) need
# their drivers in the rootfs. The kernel already builds them as modules; they
# are not installed unless something depends on them, so a modem enumerates
# with no driver bound. PPP covers dial-up fallback, tun the tunnel clients,
# and dummy gives tests a netdev that needs no hardware. pwm_fan and
# raspberrypi_hwmon run the fan and report undervoltage, uvcvideo drives USB
# cameras, and the i2c group exposes the RP1 I2C buses as /dev/i2c-* for
# watchdog and display boards.
RDEPENDS:packagegroup-avocado-rootfs-modules:append = " \
    kernel-module-usbnet-${KERNEL_VERSION} \
    kernel-module-cdc-ether-${KERNEL_VERSION} \
    kernel-module-cdc-ncm-${KERNEL_VERSION} \
    kernel-module-cdc-mbim-${KERNEL_VERSION} \
    kernel-module-cdc-wdm-${KERNEL_VERSION} \
    kernel-module-cdc-acm-${KERNEL_VERSION} \
    kernel-module-rndis-host-${KERNEL_VERSION} \
    kernel-module-qmi-wwan-${KERNEL_VERSION} \
    kernel-module-option-${KERNEL_VERSION} \
    kernel-module-usb-wwan-${KERNEL_VERSION} \
    kernel-module-usbserial-${KERNEL_VERSION} \
    kernel-module-qcserial-${KERNEL_VERSION} \
    kernel-module-sierra-${KERNEL_VERSION} \
    kernel-module-sierra-net-${KERNEL_VERSION} \
    kernel-module-ppp-generic-${KERNEL_VERSION} \
    kernel-module-ppp-async-${KERNEL_VERSION} \
    kernel-module-ppp-deflate-${KERNEL_VERSION} \
    kernel-module-slhc-${KERNEL_VERSION} \
    kernel-module-tun-${KERNEL_VERSION} \
    kernel-module-dummy-${KERNEL_VERSION} \
    kernel-module-pwm-fan-${KERNEL_VERSION} \
    kernel-module-raspberrypi-hwmon-${KERNEL_VERSION} \
    kernel-module-uvcvideo-${KERNEL_VERSION} \
    kernel-module-i2c-dev-${KERNEL_VERSION} \
    kernel-module-i2c-designware-core-${KERNEL_VERSION} \
    kernel-module-i2c-designware-platform-${KERNEL_VERSION} \
"

# Onboard Wi-Fi, Pi 5 only. Only the Pi 5 rootfs carries the CYW43455/43456
# firmware and the supplicant (packagegroup-avocado-rootfs.bbappend). On the
# other Pi boards brcmfmac would bind to the SDIO chip at boot, fail to load
# firmware the rootfs does not have, and log an error on every boot.
RDEPENDS:packagegroup-avocado-rootfs-modules:append:raspberrypi5 = " \
    kernel-module-brcmfmac-${KERNEL_VERSION} \
    kernel-module-brcmfmac-wcc-${KERNEL_VERSION} \
    kernel-module-brcmutil-${KERNEL_VERSION} \
    kernel-module-cfg80211-${KERNEL_VERSION} \
    kernel-module-rfkill-${KERNEL_VERSION} \
"
