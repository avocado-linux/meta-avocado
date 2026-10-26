DESCRIPTION = "Packagegroup for extra packages in Avocado arm64 UEFI builds"
LICENSE = "Apache-2.0"

PACKAGE_ARCH = "${MACHINE_ARCH}"

inherit packagegroup nospdx

PACKAGES = "${PN}"

# Wi-Fi/Bluetooth firmware - MediaTek MT7925 (DGX Spark)
WIFI_MEDIATEK = " \
  linux-firmware-mediatek \
"

# Wi-Fi regulatory database (cfg80211 loads regulatory.db at boot)
WIFI_REGDB = " \
  wireless-regdb-static \
"

# Ethernet firmware - Realtek RTL8127A 10GbE (DGX Spark)
ETH_REALTEK = " \
  linux-firmware-rtl-nic \
"

# arm64 server hardware management tools
HARDWARE_TOOLS = " \
  efibootmgr \
  pciutils \
  dmidecode \
  nvme-cli \
  ethtool \
"

RDEPENDS:${PN} = " \
  ${WIFI_MEDIATEK} \
  ${WIFI_REGDB} \
  ${ETH_REALTEK} \
  ${HARDWARE_TOOLS} \
  packagegroup-avocado-nvidia-gpu \
  kernel-modules \
"
