DESCRIPTION = "Packagegroup for extra packages in Avocado Intel x86-64 builds"
LICENSE = "Apache-2.0"

PACKAGE_ARCH = "${MACHINE_ARCH}"
inherit packagegroup
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

# GPU firmware - Intel
GPU_FIRMWARE = " \
  linux-firmware-i915 \
"

# CPU microcode - Intel
CPU_MICROCODE = " \
  intel-microcode \
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
  ${GPU_FIRMWARE} \
  ${CPU_MICROCODE} \
  ${HARDWARE_TOOLS} \
  packagegroup-avocado-nvidia-gpu \
  kernel-modules \
  swupdate \
"
