# Shared Avocado overrides for Rockchip RK35xx machines on top of the
# upstream Yocto Project meta-rockchip layer (git.yoctoproject.org/meta-rockchip).
#
# Required load order in machine.conf:
#   require conf/machine/include/avocado.inc
#   require conf/machine/include/rk3588.inc                    # vendor BSP
#   require conf/machine/include/avocado-rockchip.inc          # this file -- last
#
# The "last" requirement is load-bearing for IMAGE_FSTYPES:remove below;
# rk3588.inc -> rk3588s.inc -> rockchip-wic.inc adds "wic" to IMAGE_FSTYPES,
# and our :remove only takes effect when evaluated after that line.
#
# Tune (cortexa76-cortexa55-crypto) and DEFAULTTUNE come from rk3588s.inc;
# kernel provider (linux-yocto) and serial console (1500000;ttyS2) from
# rockchip-defaults.inc; KBUILD_DEFCONFIG=defconfig from rk3588s.inc. We
# don't override these.

# Stone owns image creation. rk3588s.inc requires rockchip-wic.inc which
# adds "wic" to IMAGE_FSTYPES; the bootloader deploy that wic implicitly
# pulled in is now pinned explicitly in avocado-stone.bbappend.
IMAGE_FSTYPES:remove = "wic"
IMAGE_FSTYPES:remove = "wic.bmap"

# Plain Image + separate DTB + cpio.zst initramfs in the boot FAT works
# better with stone's manifest model than fitImage's all-in-one ITB.
# rk3588s.inc sets KERNEL_IMAGETYPE = "fitImage" with ?=; override here.
KERNEL_IMAGETYPE = "Image"
KERNEL_IMAGETYPES = "Image"
