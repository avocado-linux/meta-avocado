# NVIDIA's UEFI builds edk2, edk2-platforms and edk2-nvidia from source, but sets
# no CVE_PRODUCT, so cve-check falls back to ${BPN} and the firmware that owns the
# whole early boot scans clean on every Jetson. NVD files edk2 under two spellings.
#
# The % matches edk2-firmware-tegra and edk2-firmware-tegra-rcmboot, which are the
# same sources built for two boot paths.
CVE_PRODUCT = "tianocore:edk2 tianocore:edk_ii"

# PV is the L4T release, which shares no scheme with the YYYYMM edk2-stable
# versions NVD records, so every bounded range compares true and the recipe
# reports every edk2 CVE ever filed. edk2-stable202408 is the newest stable tag
# that is an ancestor of SRCREV_edk2 c80eba3c on NVIDIA's r36.5.1-updates branch.
#
# Only edk2 needs this. optee-os 4.2 and arm-trusted-firmware 2.8 carry the same
# -l4t-r36.5.2 suffix and compare correctly against NVD's semver without help.
CVE_VERSION = "202408"

# CVE_VERSION is derived from a SRCREV this append cannot see change: bump the
# meta-tegra pin past edk2-stable202408 and a stale 202408 silently hides every
# CVE whose range starts after it. NVD carries exact-match rows for edk2, so the
# stale direction is not the safe one.
python () {
    reviewed = "c80eba3cb8aafaac243f45434f6d3a42a4145ed3"
    if d.getVar("SRCREV_edk2") != reviewed:
        bb.warn("edk2 SRCREV moved; re-derive CVE_VERSION (now %s) from the newest "
                "edk2-stable tag that is an ancestor of it" % d.getVar("CVE_VERSION"))
}
