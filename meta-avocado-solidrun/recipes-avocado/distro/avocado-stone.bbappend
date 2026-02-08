# Ensure firmware artifacts are deployed before stone runs
do_compile[depends] += "firmware-pack:do_deploy"
do_compile[depends] += "flash-writer:do_deploy"
do_compile[depends] += "u-boot:do_deploy"

DEPENDS += " jq-native mkfat-native"
