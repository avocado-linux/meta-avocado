# The boot image lists amd-ucode.cpio (stone-amd-x86-64-v4.json), so it has to
# be in DEPLOY_DIR_IMAGE before stone reads the manifest. avocado-img-bootfiles
# depends on this recipe's do_deploy, so the file also reaches the bootfiles
# package that avocado-cli's runtime bundle is built from. Scoped to the AMD
# machine: a kas config that stacks this layer for another machine must not
# start building AMD microcode it never ships.
AMD_UCODE_DEPLOY = ""
AMD_UCODE_DEPLOY:avocado-amd-x86-64 = "amd-ucode-cpio:do_deploy"
do_compile[depends] += "${AMD_UCODE_DEPLOY}"
