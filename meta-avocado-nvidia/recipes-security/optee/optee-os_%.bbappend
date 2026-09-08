# meta-tegra sets "linaro:op-tee op-tee:op-tee_os". The first is real but holds 2
# records; the bulk of OP-TEE lives under trustedfirmware:, and the second pair
# exists in no NVD record at all. Replaced rather than appended, to drop it.
#
# Not set on tos-optee or standalone-mm-optee-tegra: those assemble images out of
# this recipe's output and build no OP-TEE source, so naming them would double-count.
# optee-client is left blind on purpose, not by oversight - it ships libteec and
# tee-supplicant on every Jetson, but NVD files no product for the client alone, so
# the only name available would attribute optee_os bugs to it. Needs a decision.
CVE_PRODUCT = "trustedfirmware:op-tee linaro:op-tee"

# As with arm-trusted-firmware: the -l4t-r36.5.2 suffix reaches the SPDX and VEX
# CPEs verbatim. NVD versions OP-TEE as X.Y.Z, hence 4.2.0 rather than the recipe's
# 4.2 - identical to cve-check either way, correct only one way to a CPE consumer.
CVE_VERSION = "4.2.0"
