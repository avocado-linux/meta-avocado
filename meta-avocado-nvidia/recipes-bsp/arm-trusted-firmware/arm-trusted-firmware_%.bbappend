# meta-tegra names vendor arm:, which indexes none of these products, so three of
# its four pairs match nothing and TF-A reports one CVE instead of its real set.
# Same two pairs as meta-avocado-nxp's imx-atf append, and vendor-qualified for the
# same reason: amd: and renesas: ship unrelated forks under these product names.
CVE_PRODUCT = "trustedfirmware:trusted_firmware-a arm_trusted_firmware_project:arm_trusted_firmware"

# cve-check parses 2.8 out of the -l4t- suffix on its own, but get_cpe_ids() only
# strips +git, so the published SPDX and VEX would carry a CPE version no NVD
# record uses. Derived rather than pinned because this append matches every future
# PV: a literal would keep asserting the old version after an L4T bump, and both
# the CPE and cve-check's exact-match branch read this string verbatim.
#
# Not padded the way optee-os is: NVD spells trusted_firmware-a two-component (1.2,
# 2.0, 2.8), so PV's leading components are already the right shape. The r38/r39
# meta-tegra branches carry a 2.8.16 PV, which would emit a version no NVD row uses
# - revisit here when the pin reaches one, rather than guessing the shape now.
CVE_VERSION = "${@d.getVar('PV').split('-l4t')[0]}"
