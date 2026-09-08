# meta-tegra sets "linaro:op-tee op-tee:op-tee_os". The first is real but holds 2
# records; the bulk of OP-TEE lives under trustedfirmware:, and the second pair
# exists in no NVD record at all. Replaced rather than appended, to drop it.
#
# Not set on tos-optee or standalone-mm-optee-tegra: those assemble images out of
# this recipe's output and build no OP-TEE source, so naming them would double-count.
CVE_PRODUCT = "trustedfirmware:op-tee linaro:op-tee"
