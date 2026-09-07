SUMMARY = "ukify from systemd, for the Avocado SDK"
DESCRIPTION = "systemd's ukify, packaged for the SDK sysroot. oe-core ships it \
as systemd-boot-native (for linux-avocado-qcom-uki, which builds the UKI during \
the Yocto build); the same tool is needed inside the SDK so \
stone-provision-ufs.sh can rebuild the UKI around whichever kernel the project \
pinned, rather than shipping whatever kernel the default multiconfig happened \
to build."

# Named for the recipe it mirrors: oe-core's systemd-boot-native, which despite
# its name builds nothing and only installs src/ukify/ukify.py. This is its
# nativesdk twin, exactly as nativesdk-systemd-systemctl alongside is the twin
# of systemd-systemctl-native.
#
# A sibling recipe rather than a BBCLASSEXTEND on systemd-boot-native: that one
# does `inherit native`, which cannot also be class-extended to nativesdk. Extending the main systemd recipe is not an option either -- it
# has no BBCLASSEXTEND and inherits useradd/update-rc.d/systemd, so one Python
# script would drag all of systemd through a nativesdk build.
#
# ukify.py is pure Python and needs no configure or compile, which is why
# systemd-boot-native deltasks both; this does the same.
#
# Using the real ukify matters. Appending the PE sections by hand with objcopy
# produces an image that matches a known-good UKI on every axis objdump shows --
# section names, sizes, virtual addresses, flags, SizeOfImage -- and still will
# not boot: UEFI dies during "OS Loader" with an undefined-instruction
# exception (ESR 0x2000000) before the kernel says anything, reproduced with a
# kernel known to boot. A pefile reimplementation got to within 5 bytes of
# ukify's output (SizeOfInitializedData, and .linux marked as initialized data
# rather than code) which is exactly the kind of near-miss not worth
# maintaining when the real tool is 20 lines of packaging away.
require recipes-core/systemd/systemd.inc
FILESEXTRAPATHS =. "${FILE_DIRNAME}/systemd:"

inherit nativesdk

deltask do_configure
deltask do_compile

do_install() {
    install -Dm 0755 ${S}/src/ukify/ukify.py ${D}${bindir}/ukify
}
addtask install after do_patch

PACKAGES = "${PN}"
FILES:${PN} = "${bindir}/ukify"

RDEPENDS:${PN} += "nativesdk-python3-pefile"
