# NVIDIA's UEFI builds edk2, edk2-platforms and edk2-nvidia from source, but sets
# no CVE_PRODUCT, so cve-check falls back to ${BPN} and the firmware that owns the
# whole early boot scans clean on every Jetson. NVD files edk2 under two spellings.
#
# The % matches edk2-firmware-tegra and edk2-firmware-tegra-rcmboot, which are the
# same sources built for two boot paths.
CVE_PRODUCT = "tianocore:edk2 tianocore:edk_ii"
