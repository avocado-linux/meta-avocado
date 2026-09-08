# meta-tegra names vendor arm:, which indexes none of these products, so three of
# its four pairs match nothing and TF-A reports one CVE instead of its real set.
# Same two pairs as meta-avocado-nxp's imx-atf append, and vendor-qualified for the
# same reason: amd: and renesas: ship unrelated forks under these product names.
CVE_PRODUCT = "trustedfirmware:trusted_firmware-a arm_trusted_firmware_project:arm_trusted_firmware"
