do_compile[depends] += "systemd-boot:do_deploy"
do_compile[depends] += "systemd-bootconf:do_deploy"

# What the arm64 provisioning script runs, so do_stone_provision can build the
# disk image (and its avocado-flash archive) inside the build: jq for the
# manifest, sgdisk for the GPT, mkfs.fat and mtools for the boot partition,
# fwup for the archive. Without them do_stone_provision stops at the first jq
# call with exit 127. Scoped to the img profile, so a machine without it builds
# none of these.
DEPENDS:append:stone-img = " jq-native gptfdisk-native dosfstools-native mtools-native fwup-native"
