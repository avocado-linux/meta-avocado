# The upstream recipe in meta-raspberrypi `inherit allarch`s, but the package
# payload is machine-specific: `cyfmac43455-sdio.bin` is a symlink whose target
# changes per machine via `CYFMAC43455_SDIO_FIRMWARE:raspberrypi5 = "standard"`
# (vs the default "minimal" elsewhere). The same noarch RPM therefore differs
# byte-for-byte across builds and trips Pulp dedupe on upload.
#
# `PACKAGE_ARCH = "${MACHINE_ARCH}"` alone won't stick: allarch.bbclass
# registers a RecipePreFinalise handler that unconditionally resets PACKAGE_ARCH
# back to "all". Bbappends are parsed after the .bb, so a same-event handler
# registered here runs after allarch's and wins.

PACKAGE_ARCH = "${MACHINE_ARCH}"

python force_machine_arch_post_allarch () {
    d.setVar("PACKAGE_ARCH", d.getVar("MACHINE_ARCH"))
}
addhandler force_machine_arch_post_allarch
force_machine_arch_post_allarch[eventmask] = "bb.event.RecipePreFinalise"
