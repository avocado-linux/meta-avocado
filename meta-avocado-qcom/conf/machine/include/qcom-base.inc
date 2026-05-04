SOC_FAMILY:prepend = "qcom:"
require conf/machine/include/soc-family.inc

# Skip chromium-ozone-wayland on qcom: chromium 146 (backported into
# meta-avocado-distro on 2026-04-05, see distro/backports.json) requires
# wayland-server >= 1.24.0 for ANGLE's wayland_egl, but OE-core scarthgap
# ships wayland 1.22.0. Drop chromium from packagegroup-avocado-extra's
# BROWSER_PACKAGES until either wayland is bumped distro-wide or chromium
# is downgraded back to 138 (the meta-browser/scarthgap shipped version).
# Uses :qcom override (applied at expansion) so it trumps the recipe-level
# BROWSER_PACKAGES = "chromium-ozone-wayland" set in packagegroup-avocado-
# extra.bb.
BROWSER_PACKAGES:qcom = ""

#Define and add SOC_ARCH to the list of architectures compatible with the given target.
SOC_ARCH = "${@ d.getVar('SOC_FAMILY').replace('-', '_').replace('qcom:', '')}"
PACKAGE_EXTRA_ARCHS:append = "${@['', ' ${SOC_ARCH}']['${SOC_ARCH}' != "${MACHINE_ARCH}"]}"

# Supported BSP selections are: base, custom
# We intend to use 'custom' BSP by default.
# Specific MACHINEs or DISTROs might change this as needed.
QCOM_SELECTED_BSP ??= "custom"
MACHINEOVERRIDES =. "qcom-${QCOM_SELECTED_BSP}-bsp:"

# Set prebuilt pkgs default arch
PBT_ARCH ?= "${SOC_ARCH}"

# Provider for Graphics Library.
# qcom-base-bsp uses 'mesa' as GL provider
GL_PROVIDER ?= "qcom-adreno"
GL_PROVIDER:qcom-base-bsp ?= "mesa"

PREFERRED_PROVIDER_virtual/egl      = "${GL_PROVIDER}"
PREFERRED_PROVIDER_virtual/libgles1 = "${GL_PROVIDER}"
PREFERRED_PROVIDER_virtual/libgles2 = "${GL_PROVIDER}"

PREFERRED_PROVIDER_virtual/egl-native      = "mesa-native"
PREFERRED_PROVIDER_virtual/libgl-native    = "mesa-native"
PREFERRED_PROVIDER_virtual/libgles1-native = "mesa-native"
PREFERRED_PROVIDER_virtual/libgles2-native = "mesa-native"
PREFERRED_PROVIDER_virtual/libgbm-native   = "mesa-native"

# Provider for libgbm
PREFERRED_PROVIDER_virtual/libqbm ?= "qbm"
PREFERRED_PROVIDER_virtual/libgbm = "${@'msm' if d.getVar('GL_PROVIDER') == 'qcom-adreno' else 'mesa'}"

# Provider for linux kernel
# qcom-base-bsp uses 'linux-qcom-base' as kernel
PREFERRED_PROVIDER_virtual/kernel ?= "linux-qcom-custom"
PREFERRED_PROVIDER_virtual/kernel:qcom-base-bsp ?= "linux-qcom-base"

KERNEL_IMAGETYPE ?= "Image"
KERNEL_ALT_IMAGETYPE ?= "vmlinux"

# Recipe provider for boot critical nhlos bins
PREFERRED_PROVIDER_virtual/bootbins ?= "firmware-qcom-bootbins"

# Recipe provider for disk partition configuration
PREFERRED_PROVIDER_virtual/partconf ?= "firmware-qcom-partconf"

PREFERRED_PROVIDER_android-tools-conf = "android-tools-conf-configfs"

# qcom-flavored modemmanager / libqmi / libqrtr-glib (cellular modem stack)
# were carried by older meta-qcom-hwe; current upstream ships vanilla
# versions only. The rubikpi3 dev kit has no onboard cellular modem, so the
# vanilla upstream versions are sufficient. Re-pin if a future qcom machine
# needs the qcom-flavored stack.

#Use qcom specific version of wpa-supplicant in custom-bsp
PREFERRED_VERSION_wpa-supplicant = "2.11"
PREFERRED_VERSION_wpa-supplicant:qcom-custom-bsp = "2.10.qcom"

#Use qcom specific version of fastrpc in custom-bsp
PREFERRED_VERSION_fastrpc:qcom-custom-bsp ?= "15.0.qcom"
#Use upstream fastrpc in base-bsp
PREFERRED_VERSION_fastrpc:qcom-base-bsp ?= "0.0+"

#Use version of libvirt from meta-qcom-hwe
PREFERRED_VERSION_libvirt = "9.2.0"

#Use version of android-tools from meta-openembedded
PREFERRED_VERSION_android-tools ?= "5.1.1.r37"

# For module signing
INHERIT += " qmodule"

# UFS LBA alignment — qdl writes raw bytes per rawprogram XML and the firehose
# programmer requires partition source files to be a multiple of 4096 bytes.
IMAGE_ROOTFS_ALIGNMENT = "4096"

# meta-ros's libcamera 0.5.2 (the version BitBake picks via highest-PV) defaults
# LIBCAMERA_PIPELINES to "auto", which probes the rpi/pisp pipeline. That
# pipeline requires libpisp from meta-raspberrypi (not in our build), and
# meson's wrap-fallback subproject download is disabled in OE, so configure
# fails. Restrict to pipelines that don't drag in board-specific deps.
LIBCAMERA_PIPELINES = "simple,uvcvideo,vimc"

# system.img (rootfs) is no longer staged at yocto time — stone-provision-ufs.sh
# injects avocado-cli's runtime-built erofs-lz4 at provision time. So the
# `SYSTEMIMAGE_TYPE` knob in image-avocado-qcom-deploy.bbclass (defaulting to
# "squashfs") is unused for our flow; left untouched.

#Add options to ota-esp
EXTRA_IMAGECMD:ota-ext4:append = " -O encrypt,stable_inodes"

# Mask out tar.gz from IMAGE_FSTYPES
IMAGE_TYPES_MASKED = "tar.gz"

# Default serial console for QCOM devices
SERIAL_CONSOLES ??= "115200;ttyMSM0"

INITRAMFS_MAXSIZE = "393216"

# Boot image settings
QCOM_BOOTIMG_KERNEL_BASE ?= "0x80000000"
QCOM_BOOTIMG_PAGE_SIZE ?= "4096"
QCOM_BOOTIMG_ROOTFS ?= "/dev/disk/by-partlabel/system"

#
# Below are variables are backport from meta/conf/image-uefi.conf master branch
#
EFI_ARCH = "aa64"

# Location of UKI inside EFI System Partition
EFI_UKI_DIR ?= "/EFI/Linux"
EFI_UKI_PATH = "${EFI_PREFIX}${EFI_UKI_DIR}"

# Use systemd-boot as the EFI bootloader
EFI_PROVIDER = "systemd-boot"

# Install packages at root of ESP
EFI_PREFIX = ""

# Location of dtb inside ESP
EFI_DTB_DIR ?= "${EFI_PREFIX}dtb"

# Unified Kernel Image (UKI) name
EFI_LINUX_IMG ?= "linux-${MACHINE}.efi"

# Place dtb at EFIDTDIR to seamlessly package
KERNEL_DTBDEST = "${EFI_DTB_DIR}"

CORE_IMAGE_EXTRA_INSTALL:sota += "efimount"
CORE_IMAGE_EXTRA_INSTALL:sota += "varmount"
IMAGE_CLASSES += "image_types_ota_sdboot"
