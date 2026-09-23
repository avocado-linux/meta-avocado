DESCRIPTION = "Packagegroup for extra packages in Avocado AMD x86-64 builds"
LICENSE = "Apache-2.0"

PACKAGE_ARCH = "${MACHINE_ARCH}"
inherit packagegroup nospdx
PACKAGES = "${PN}"

# WiFi firmware - Qualcomm/Atheros (common on AMD platforms)
WIFI_ATHEROS = " \
  linux-firmware-ath10k \
  linux-firmware-ath11k \
"

# WiFi firmware - Realtek (common on AMD platforms)
WIFI_REALTEK = " \
  linux-firmware-rtl8192ce \
  linux-firmware-rtl8192cu \
  linux-firmware-rtl8723 \
  linux-firmware-rtl8821 \
"

# Bluetooth firmware
BT_FIRMWARE = " \
  linux-firmware-ibt \
"

# GPU firmware - AMD
GPU_FIRMWARE = " \
  linux-firmware-amdgpu-misc \
"

# CPU microcode - AMD
CPU_MICROCODE = " \
  linux-firmware-amd-ucode \
"

# WiFi and Bluetooth userspace tools
WIRELESS_TOOLS = " \
  wpa-supplicant \
  iw \
  bluez5 \
"

# x86-64 hardware management tools
HARDWARE_TOOLS = " \
  efibootmgr \
  tpm2-tools \
  pciutils \
  dmidecode \
  nvme-cli \
  smartmontools \
"

RDEPENDS:${PN} = " \
  ${WIFI_ATHEROS} \
  ${WIFI_REALTEK} \
  ${BT_FIRMWARE} \
  ${GPU_FIRMWARE} \
  ${CPU_MICROCODE} \
  ${WIRELESS_TOOLS} \
  ${HARDWARE_TOOLS} \
  kernel-modules \
  swupdate \
"
