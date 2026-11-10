DESCRIPTION = "Packagegroup for extra packages in Avocado Intel x86-64 builds"
LICENSE = "Apache-2.0"

PACKAGE_ARCH = "${MACHINE_ARCH}"
inherit packagegroup nospdx
PACKAGES = "${PN}"

# WiFi firmware - Intel
WIFI_INTEL = " \
  linux-firmware-iwlwifi \
"

# WiFi firmware - Qualcomm/Atheros (common on Intel platforms)
WIFI_ATHEROS = " \
  linux-firmware-ath10k \
  linux-firmware-ath11k \
"

# WiFi firmware - Realtek (common on Intel platforms)
WIFI_REALTEK = " \
  linux-firmware-rtl8192ce \
  linux-firmware-rtl8192cu \
  linux-firmware-rtl8723 \
  linux-firmware-rtl8821 \
"

# Ethernet firmware - Realtek RTL8111/8125 (r8169), common on Celeron and
# Atom boards
ETH_FIRMWARE = " \
  linux-firmware-rtl-nic \
"

# Bluetooth firmware - Intel
BT_FIRMWARE = " \
  linux-firmware-ibt \
"

# GPU firmware - Intel
GPU_FIRMWARE = " \
  linux-firmware-i915 \
"

# Intel iGPU media and compute: the VA-API driver (iHD, Gen9 and later) and
# vainfo; oneVPL with its GPU runtime (Gen12 and later); Vulkan (ANV) with
# vulkaninfo (the loader is listed itself: vulkaninfo and applications dlopen
# it, so nothing depends on it); and the firmware the xe driver loads (Lunar
# Lake and later).
# libva alone has no Intel backend.
GPU_MEDIA = " \
  intel-media-driver \
  libva-utils \
  libvpl \
  vpl-gpu-rt \
  mesa-vulkan-drivers \
  vulkan-loader \
  vulkan-tools \
  linux-firmware-xe \
"

# CPU microcode - Intel
CPU_MICROCODE = " \
  intel-microcode \
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
  ${WIFI_INTEL} \
  ${WIFI_ATHEROS} \
  ${WIFI_REALTEK} \
  ${ETH_FIRMWARE} \
  ${BT_FIRMWARE} \
  ${GPU_FIRMWARE} \
  ${GPU_MEDIA} \
  ${CPU_MICROCODE} \
  ${WIRELESS_TOOLS} \
  ${HARDWARE_TOOLS} \
  packagegroup-avocado-nvidia-gpu \
  kernel-modules \
  swupdate \
"
