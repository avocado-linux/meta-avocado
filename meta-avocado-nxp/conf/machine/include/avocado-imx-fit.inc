# Boot the kernel, device tree and initramfs as ONE FIT via `bootm`, signed when
# the verified-boot DISTRO_FEATURE is on and unsigned otherwise. Required by any
# u-boot-imx machine whose env boots `fitImage` (avocado-imx93-frdm and
# avocado-imx8mp-evk today). A machine that requires this must also:
#   - set FIT_CONF_DEFAULT_DTB to the dtb its env used to boot, and
#   - have a stone manifest whose boot partition carries "fitImage", and a
#     u-boot env whose avocado_boot is `bootm ${image_addr}`.
# The FIT itself is assembled by avocado-imx-fitimage.bb, which avocado-stone's
# bbappend depends on for any machine carrying kernel-fit-extra-artifacts.
#
# FIT signing is gated here, not per-recipe: avocado-imx-fitimage.bb
# (kernel-fit-image.bbclass) and u-boot-imx_%.bbappend (uboot-sign.bbclass)
# are two DIFFERENT recipes with two separate datastores, and both need to
# see the same verified-boot decision. A machine-conf variable is resolved
# before any recipe parses, so it's the one place both recipes read the same
# value from - a recipe-local d.setVar() in either bbappend would be invisible
# to the other. "0", not "" - kernel-fit-image.bbclass passes this through
# oe.types.boolean(), which raises ValueError on anything outside its
# explicit token list ('0'/'1'/'yes'/'no'/...); an empty string is NOT
# accepted as falsy there, confirmed by a real build.
UBOOT_SIGN_ENABLE = "${@bb.utils.contains('DISTRO_FEATURES', 'verified-boot', '1', '0', d)}"
UBOOT_SIGN_KEYDIR = "${@bb.utils.contains('DISTRO_FEATURES', 'verified-boot', d.getVar('AVOCADO_SB_KEYS_DIR') or '', '', d)}"
UBOOT_SIGN_KEYNAME = "${@bb.utils.contains('DISTRO_FEATURES', 'verified-boot', 'FIT', '', d)}"

# kernel-fit-image.bbclass defaults these three to "${UBOOT_SIGN_ENABLE}" etc.
# via a weak `?=`, but on the fitimage recipe's own datastore that weak default
# resolved to an empty string rather than inheriting UBOOT_SIGN_ENABLE's value,
# crashing do_compile with oe.types.boolean(''). Setting them explicitly and
# strongly here removes the weak-default resolution from the picture entirely -
# confirmed by a real build: `mkimage -l` on the produced fitImage shows
# `Sign algo: sha256,rsa2048:FIT` on its configuration node.
FIT_KERNEL_SIGN_ENABLE = "${UBOOT_SIGN_ENABLE}"
FIT_KERNEL_SIGN_KEYDIR = "${UBOOT_SIGN_KEYDIR}"
FIT_KERNEL_SIGN_KEYNAME = "${UBOOT_SIGN_KEYNAME}"

# kernel-fit-image.bbclass reads linux.bin/linux_comp from the kernel's deploy
# dir, and oe-core's own mechanism for producing them is this class - named as
# the requirement in kernel-fit-image.bbclass ("This bbclass requires
# KERNEL_CLASSES += kernel-fit-extra-artifacts") and already used by eleven
# meta-freescale ls*.conf machines. Set in machine conf rather than the kernel
# bbappend: a machine conf resolves before any recipe parses, so there is no
# question of kernel.bbclass's inherit_defer having already run; and it keeps
# the extra objcopy+gzip per deploy off i.MX boards still booting loose files.
# Its presence is also what avocado-stone.bbappend keys the fitimage dependency on.
KERNEL_CLASSES:append = " kernel-fit-extra-artifacts"

# This include deliberately does NOT override INITRAMFS_IMAGE_BUNDLE, so the
# distro default in conf/distro/avocado.conf ("0") applies and the initramfs
# rides in the FIT as its own signed ramdisk-1 node rather than being folded
# into the kernel image. Bundling a 134 MiB uncompressed initramfs into the
# kernel gave a 167.9 MiB decompression target on imx93-frdm - past
# CONFIG_SYS_BOOTM_LEN on both the board's u-boot (0x8000000) and ours
# (0x4000000), so bootm aborted with "Image too large". Unbundled, the limit
# only ever has to cover the kernel and initramfs growth is unbounded by it.
# Signature coverage is unchanged: oe/fitimage.py appends "ramdisk" to the
# configuration node's sign_entries alongside "kernel" and "fdt".
