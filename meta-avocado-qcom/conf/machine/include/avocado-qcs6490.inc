# Shared machine settings for QCS6490 / QCM6490 (Kodiak) boards.
#
# Everything here is a property of the SoC and of how avocado boots it, not of
# any one board: the boot chain's shape, the UART, the ESP/UKI arrangement and
# the partition labels the provisioning script and the OS update path agree on.
# A board conf requires this and then declares only what is genuinely its own --
# its device tree, its boot binaries, its peripherals.
#
# Boards using this: avocado-rubikpi3, avocado-rb3gen2.

STONE_PROVISIONING ?= "ufs noop"

require conf/machine/include/avocado.inc
# meta-qcom's SoC include: qcm6490 SOC_FAMILY, armv8-2a-crypto tune,
# qcom-base.inc (linux-qcom, linux-qcom-dtbbin) and qcom-common.inc.
require conf/machine/include/qcom-qcs6490.inc

# Kernel: Qualcomm's upstream-tracking linux-qcom 6.18 from meta-qcom.
PREFERRED_PROVIDER_virtual/kernel = "linux-qcom"
# linux-avocado-qcom-uki packs the uncompressed Image; meta-qcom defaults to
# Image.gz for its own boot images.
KERNEL_IMAGETYPES = "Image"

# swiotlb=128 and mitigations=auto are SoC-level; net.ifnames=0 is the distro's
# interface-naming choice; pcie_pme=nomsi is needed by every Kodiak board seen
# so far (PME over MSI wedges the root complex during enumeration). A board that
# disagrees can set its own, since this is a weak assignment.
KERNEL_CMDLINE_EXTRA ?= "pcie_pme=nomsi swiotlb=128 mitigations=auto net.ifnames=0"

# meta-qcom appends ext4 + qcomflash for its qcomflash artifacts; avocado
# builds its own erofs/btrfs images and the UFS bundle, so keep them out.
IMAGE_FSTYPES:remove = "ext4 qcomflash"

# Flash the KVM XBL config rather than the stock one, which is the Gunyah
# config: under it Gunyah owns EL2, Linux boots at EL1 and /dev/kvm never
# appears whatever the kernel config says. Nothing in this distro talks to
# Gunyah -- the only Gunyah-aware driver in the kernel is a watchdog, which
# simply does not probe -- and KVM is what the qcs6490 users are asking for.
#
# Both the Thundercomm prebuilt set and Qualcomm's own public QCM6490
# bootbinaries package carry xbl_config.elf, xbl_config_gunyah.elf and
# xbl_config_kvm.elf at identical sizes, so this selection works the same way on
# either boot chain. Set it back to "gunyah" and reflash if a board needs that.
QCOM_XBL_CONFIG_VARIANT = "kvm"

# Slot a. Every board here uses the same OS layout: an ESP holding the boot
# entries, system_a/system_b for the rootfs, and one var partition. The
# avocado-build hook rewrites root= per slot when it builds the two entries, so
# this is the provisioned default rather than the only value.
QCOM_BOOTIMG_ROOTFS = "/dev/disk/by-partlabel/system_a"
AVOCADO_VAR_PART_DEV = "/dev/disk/by-partlabel/avocado"

# The SoC's debug UART, wired out on every board so far.
CONSOLE_CMDLINE ?= "console=ttyMSM0,115200n8 earlycon"
SERIAL_CONSOLES ?= "115200;ttyMSM0"

# Keep esp-avocado-qcom-image's rootfs across builds. rm_work.bbclass hangs
# rm_work_rootfs off do_image_complete as a postfunc, with
# rm_work_rootfs[cleandirs] = "${WORKDIR}/rootfs", so the tree is deleted the
# moment the image is packed. That is fine until a later build re-runs the
# image tasks WITHOUT do_rootfs -- whose stamp is still valid, so it does not
# re-run -- and mkfs.fat is handed an empty directory:
#
#   .../esp-avocado-qcom-image/1.0/rootfs/*: No such file or directory
#
# which reads as a broken image recipe rather than a deleted input. The ESP
# holds the boot entries and systemd-boot, so keeping it costs ~100 MB of work
# dir. Drop this line if that matters more than the failure mode; the manual
# recovery is `bitbake -c clean esp-avocado-qcom-image`.
RM_WORK_EXCLUDE += "esp-avocado-qcom-image"
