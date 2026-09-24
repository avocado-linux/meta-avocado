# The boot image lists amd-ucode.cpio (stone-amd-x86-64-v4.json), so it has to
# be in DEPLOY_DIR_IMAGE before stone reads the manifest. avocado-img-bootfiles
# depends on this recipe's do_deploy, so the file also reaches the bootfiles
# package that avocado-cli's runtime bundle is built from.
do_compile[depends] += "amd-ucode-cpio:do_deploy"
