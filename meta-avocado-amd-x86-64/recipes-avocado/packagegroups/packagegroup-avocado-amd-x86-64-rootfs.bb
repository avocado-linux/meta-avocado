DESCRIPTION = "Packagegroup for AMD x86-64 base rootfs packages (loaded before extensions)"
LICENSE = "Apache-2.0"

PACKAGE_ARCH = "${MACHINE_ARCH}"
inherit packagegroup nospdx
PACKAGES = "${PN}"

# The Radeon 780M (Phoenix/Hawk Point) will not initialize without its
# DMCUB/GC/PSP/SDMA/VCN blobs, and amdgpu probes before any extension is
# merged, so the firmware has to be in the base rootfs rather than the
# extras feed. oe-core ships no Phoenix-specific split; its blobs land in
# -misc. CPU microcode is not here: it only takes effect from the early
# initrd, which amd-ucode-cpio provides.
GPU_FIRMWARE = " \
  linux-firmware-amdgpu-misc \
"

RDEPENDS:${PN} = " \
  ${GPU_FIRMWARE} \
"
