# NVD indexes NXP's TF-A fork under these two names. The ${BPN} default matches
# nothing, so the secure firmware chain scans clean on every i.MX board. Kept
# vendor-qualified to exclude the amd: and renesas: forks.
CVE_PRODUCT = "trustedfirmware:trusted_firmware-a arm_trusted_firmware_project:arm_trusted_firmware"
