# The package copies DEPLOY_DIR_IMAGE, but only avocado-stone and the kernel
# were task dependencies: a rebuilt U-Boot or TF-A changed the FIP in deploy
# and the package kept the old one (same task hash). Depend on everything the
# rzv2n stone bundle ships, as avocado-stone.bbappend does.
do_compile[depends] += "firmware-pack:do_deploy"
do_compile[depends] += "flash-writer:do_deploy"
do_compile[depends] += "u-boot:do_deploy"
do_compile[depends] += "extlinux-rzv2n-sr-som:do_deploy"
