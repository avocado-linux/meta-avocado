FILESEXTRAPATHS:prepend := "${THISDIR}/files:"
SRC_URI += " \
  file://avocado-core.cfg \
  file://avocado-extra.cfg \
  file://avocado-wireless.cfg \
  file://avocado-netfilter.cfg \
  file://avocado-usb-serial.cfg \
"

# ftpm.cfg is unconditional rather than gated on the optee-ftpm feature: it only
# builds a module, and without meta-arm there is no TA for OP-TEE to advertise,
# so no microsoft,ftpm DT node exists and nothing loads it. Gating a kernel
# fragment on a feature that lives in a kas layer set would mean two kernel
# configurations for one board, which costs more than the module does.
SRC_URI:append:avocado-imx93-frdm = " \
  file://imx93-frdm/dm-crypt.cfg \
  file://imx93-frdm/ftpm.cfg \
"

SRC_URI:append:avocado-imx8mp-evk = " file://imx8mp-evk/mwifiex.cfg"

do_configure:append() {
  cat ${UNPACKDIR}/*.cfg >> ${B}/.config
  # UNPACKDIR, not WORKDIR: the stack was written against scarthgap, where
  # unpacked sources still landed in WORKDIR. Globbed there this matches nothing
  # and the fragments are dropped silently, leaving a kernel with no
  # CONFIG_DM_CRYPT and a /var that cannot be unlocked.
  # `if`, not `[ -e ] &&`: on boards without this directory the glob stays
  # literal, the test is false, and that 1 would be the function's exit
  # status - do_configure failed on every non-imx93 machine that way.
  for f in ${UNPACKDIR}/*/*.cfg; do
    if [ -e "$f" ]; then cat "$f" >> ${B}/.config; fi
  done
}

inherit avocado-kernel-feed
inherit avocado-kernel-builtin-provides
require recipes-kernel/linux/avocado-kernel-modules-packagegroup.inc

# FIT image assembly for avocado-imx93-frdm is NOT wired here. This oe-core
# release's kernel.bbclass explicitly rejects KERNEL_IMAGETYPE=fitImage
# ("fitImage is no longer supported as a KERNEL_IMAGETYPE(S). FIT images are
# built by the linux-yocto-fitimage recipe") - kernel-fitimage.bbclass was
# replaced by kernel-fit-image.bbclass, used as its OWN dedicated recipe that
# depends on virtual/kernel:do_deploy rather than something inherited into
# the kernel recipe itself. See avocado-imx93-frdm-fitimage.bb.
#
# linux.bin/linux_comp, which kernel-fit-image.bbclass reads, are produced by
# oe-core's kernel-fit-extra-artifacts.bbclass. It is selected via
# KERNEL_CLASSES in avocado-imx93-frdm.conf, not from here - see that file.
#
# An earlier revision of this bbappend hand-wrote that class's body here
# (`inherit kernel-uboot` plus a do_deploy:append calling uboot_prep_kimage),
# under a comment claiming no upstream mechanism existed. Three things were
# wrong with it. The class does exist and is named as the requirement in
# kernel-fit-image.bbclass itself. The `inherit kernel-uboot` was a no-op
# anyway, since kernel.bbclass defaults KERNEL_CLASSES to kernel-uimage, which
# already inherits it. And passing "${DEPLOYDIR}" rather than the class's
# "$deployDir" drops KERNEL_DEPLOYSUBDIR, so any machine built with
# KERNEL_PACKAGE_NAME != "kernel" - this repo ships multi-kernel-jetson.yml and
# multi-kernel-raspberrypi.yml, so the pattern is live - would put linux.bin one
# directory above where the FIT recipe looks, reproducing the exact
# FileNotFoundError the hand-rolled version was written to fix.
