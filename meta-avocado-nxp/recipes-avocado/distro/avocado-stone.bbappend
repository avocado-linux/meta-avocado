# Depend on whichever bootloader the machine selects (u-boot-imx for the NXP
# EVK/FRDM, u-boot-compulab for CompuLab boards), not a hardcoded recipe -
# forcing u-boot-imx on a CompuLab machine fails (no defconfig for it).
do_compile[depends] += "${IMX_DEFAULT_BOOTLOADER}:do_deploy"
do_compile[depends] += "imx-boot:do_deploy"

DEPENDS += " jq-native mkfat-native fwup-native"

# fw_setenv, for stone-provision-uuu-emmc.sh, which patches devnum and mmcblk
# into the U-Boot environment inside the disk image before writing it. jq and
# fwup arrive above; fw_setenv had no provider, so do_stone_provision died with
# "fw_setenv: command not found" the first time that profile was selected.
# libubootenv ships it (it also PROVIDES u-boot-fw-utils).
#
# Scoped to the profile that calls it rather than added to the shared
# avocado-stone.bb: 5 of the 30 avocado-*.conf machines list uuu-emmc in
# STONE_PROVISIONING, and the other 25 would build a native package for a
# script they never deploy.
DEPENDS:append:stone-uuu-emmc = " libubootenv-native"

SRC_URI += " \
    file://rootdisk.conf \
"

SRC_URI:append:stone-uuu-emmc = " \
    file://stone-provision-uuu-emmc.sh \
"

do_deploy:append() {
  install -d ${DEPLOYDIR}
  install -m 0644 ${UNPACKDIR}/rootdisk.conf ${DEPLOYDIR}/rootdisk.conf
}

do_deploy:append:stone-uuu-emmc() {
  install -d ${DEPLOYDIR}
  install -m 0755 ${UNPACKDIR}/stone-provision-uuu-emmc.sh ${DEPLOYDIR}/stone-provision-uuu-emmc.sh
}

# With AHAB on, the boot partition carries a signed OS container instead of a
# bare Image, dtb and initramfs. U-Boot's booti takes the container address and
# reads the kernel and fdt destinations back out of it (cmd/booti.c), and the
# initramfs is bundled into the kernel Image, so none of the three is loaded.
#
# Dropping the initramfs is not just tidiness. It is 44 MB against a 128 MB
# partition that now holds an ~80 MB container, and a copy left on disk is one
# an attacker can point a modified environment at.
#
# Rewritten here rather than forked into a second machine JSON: the file list
# is the only difference, and two near-identical manifests drift.
DEPENDS:append = "${@bb.utils.contains('DISTRO_FEATURES', 'ahab', ' avocado-os-container', '', d)}"
do_compile[depends] += "${@bb.utils.contains('DISTRO_FEATURES', 'ahab', 'avocado-os-container:do_deploy', '', d)}"

do_deploy:append() {
    if ${@bb.utils.contains('DISTRO_FEATURES', 'ahab', 'true', 'false', d)}; then
        _m="${DEPLOYDIR}/stone-${MACHINE_SHORT_NAME}.json"
        jq '(.storage_devices.rootdisk.images.boot.build_args.files) |=
                (map(select(. != "Image"
                            and (endswith(".dtb") | not)
                            and (startswith("avocado-image-initramfs") | not)))
                 + ["os_cntr_signed.bin"])' \
            "$_m" > "$_m.ahab" || bbfatal "failed to rewrite the boot file list for AHAB"
        mv "$_m.ahab" "$_m"

        if ! grep -q 'os_cntr_signed.bin' "$_m"; then
            bbfatal "AHAB is enabled but the boot partition still has no signed OS container"
        fi
        if grep -q '"Image"' "$_m"; then
            bbfatal "AHAB is enabled but the boot partition still ships a bare Image"
        fi
        if grep -q 'avocado-image-initramfs' "$_m"; then
            bbfatal "AHAB is enabled but the boot partition still ships a loose initramfs; it rides inside the signed container, and a second copy is both unauthenticated and 44 MB of a 128 MB partition"
        fi
    fi
}
