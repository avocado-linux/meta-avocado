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
