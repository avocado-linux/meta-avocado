# Ensure TOS image is deployed to images directory for stone validation
# The base recipe already has do_deploy task that creates:
#   - ${TOS_IMAGE}: tos-${MACHINE}-${PV}-${PR}.img (versioned)
#   - ${TOS_SYMLINK}: tos-${MACHINE}.img (symlink)
# This bbappend exists to ensure the recipe is built for Avocado Jetson machines

# Ensure tos-optee is deployed for stone validation
# The symlink tos-${MACHINE}.img is what stone manifests reference
