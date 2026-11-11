do_compile[depends] += "systemd-boot:do_deploy"
do_compile[depends] += "systemd-bootconf:do_deploy"

# What stone-provision-img.sh runs, so do_stone_provision can build the disk
# image (and its avocado-flash archive) inside the build rather than only from
# the SDK: jq for the manifest, sgdisk for the GPT, mkfs.fat and mtools for the
# boot partition, fwup for the archive. Without them do_stone_provision dies at
# the first jq call. Scoped to the img profile, like the NXP layer's uuu-emmc
# tools, so a machine without it builds none of these.
DEPENDS:append:stone-img = " jq-native gptfdisk-native dosfstools-native mtools-native fwup-native"

# The boot image lists microcode.cpio (stone-intel-x86-64-v*.json): meta-intel's
# intel-microcode deploys it as an uncompressed early-initrd cpio, and the
# loader entry passes it ahead of the initramfs. Late loading is off in the
# kernel, so a copy under /lib/firmware is never applied. The amd-ucode-cpio
# pattern; scoped to the Intel machines.
INTEL_UCODE_DEPLOY = ""
INTEL_UCODE_DEPLOY:avocado-x86-64 = "intel-microcode:do_deploy"
do_compile[depends] += "${INTEL_UCODE_DEPLOY}"
