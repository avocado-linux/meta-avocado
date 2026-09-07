FILESEXTRAPATHS:prepend := "${THISDIR}/${PN}:"

RDEPENDS:${PN}:append = "\
    nativesdk-coreutils \
    nativesdk-util-linux \
    nativesdk-util-linux-getopt \
    nativesdk-util-linux-hexdump \
    nativesdk-util-linux-mount \
    nativesdk-gptfdisk \
    nativesdk-qemu-system-x86-64 \
    nativesdk-python3-pyyaml \
    nativesdk-libxml2 \
    nativesdk-libusb1 \
    nativesdk-qdl \
    ${QCOM_SDK_UKI_TOOLS}"

# DEPENDS as well as RDEPENDS. RDEPENDS on its own only records the runtime
# requirement in the package metadata -- it does not put the provider in the
# build graph, so nothing ever builds it, it never reaches the feed, and
# `avocado sdk install` fails with "No match for argument: <pkg>" long after
# the Yocto build reported success. The stone-usb / nativesdk-libusb1 pair in
# the base recipe does exactly this for the same reason.
DEPENDS:append = " ${QCOM_SDK_UKI_TOOLS}"

# Tool stone-provision-ufs.sh needs to put the PINNED kernel into the ESP.
#
# The board boots a UKI out of efi.bin inside the yocto-static bootfiles
# bundle, and linux-avocado-qcom-uki builds that UKI from the default
# multiconfig's Image. So it is always the stock kernel, whatever
# `kernel.version` the project pinned -- and once the feed carries two kernels
# the rootfs gets one kernel's modules while the ESP boots the other, leaving
# /lib/modules matching no running kernel and every modular driver dead
# (on this board that is ethernet, wifi and thermal in one go).
#
# avocado-cli already hands the provision hook what is needed to fix it:
# AVOCADO_PROVISION_KERNEL_IMAGE / _VERSION point at the pinned kernel
# (/opt/_avocado/<target>/kernel/<kver>/Image, or the rootfs/boot fallback).
# stone-provision-ufs.sh rebuilds the UKI around it and writes it back into
# efi.bin, the same way it already injects the runtime-built rootfs and var.
#
# mtools writes the rebuilt UKI back into the FAT efi.bin in place. ukify --
# from nativesdk-systemd-boot -- is what builds it, the same tool
# linux-avocado-qcom-uki already uses during the Yocto build, so the rebuilt
# UKI is produced exactly the way the working one was.
#
# Two hand-rolled alternatives were tried first and both are recorded because
# each looks reasonable and neither works:
#
#   objcopy --add-section (already in the SDK, no new packages) produces an
#     image identical to a known-good UKI on every axis objdump reports --
#     section names, sizes, virtual addresses, flags, SizeOfImage -- and still
#     cannot boot. UEFI takes an undefined-instruction exception
#     (ESR 0x2000000) during "OS Loader" before the kernel emits anything,
#     reproduced with a kernel known to boot. objcopy is not dependable when it
#     rewrites a PE whose section table grows.
#
#   A pefile reimplementation got within 5 bytes of ukify's output, differing
#     only on SizeOfInitializedData and on marking .linux as initialized data
#     rather than code. Close enough to look right, not close enough to trust,
#     and pointless once ukify itself is 20 lines of packaging away.
#
QCOM_SDK_UKI_TOOLS = "\
    nativesdk-mtools \
    nativesdk-systemd-boot \
"
