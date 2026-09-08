# meta-tegra sets "linaro:op-tee op-tee:op-tee_os". The first is real but holds 2
# records; the bulk of OP-TEE lives under trustedfirmware:, and the second pair
# exists in no NVD record at all. Replaced rather than appended, to drop it.
#
# Deliberately not set on the three siblings, for three different reasons:
#   tos-optee            nopackages, assembles an image out of this recipe's and
#                        arm-trusted-firmware's output, builds no source at all.
#   optee-os-tadevkit    compiles this same source but installs only headers and
#                        mk fragments under ${includedir}/optee; no runtime code
#                        ships, and naming it would double-count every optee_os
#                        CVE against the same tree.
#   standalone-mm-optee-tegra
#                        builds no OP-TEE source either - but it does compile
#                        edk2, so it is covered under that lens instead, in
#                        recipes-bsp/uefi/edk2-cve.inc.
#
# optee-client is left blind on purpose, not by oversight - it ships libteec and
# tee-supplicant on every Jetson, but NVD files no product for the client alone, so
# the only name available would attribute optee_os bugs to it. Needs a decision.
CVE_PRODUCT = "trustedfirmware:op-tee linaro:op-tee"

# As with arm-trusted-firmware: the -l4t- suffix reaches the SPDX and VEX CPEs
# verbatim. NVD versions OP-TEE as X.Y.Z throughout (3.3.0, 4.3.0, 4.5.0, 4.10.0),
# so the value is padded to exactly three components; oe.cve_check._cmpkey drops a
# trailing zero again for the range compares, and no NVD op-tee row uses operator
# '=' at 4.2 or 4.2.0, so cve-check's string-compare branch is unaffected either
# way. Padded rather than suffixed because other meta-tegra branches already spell
# PV three-component (scarthgap-l4t-r35.x ships optee-os_3.21.0-l4t-r35.6.4), and a
# bare .0 would publish 3.21.0.0 there - a string no NVD record uses.
CVE_VERSION = "${@'.'.join((d.getVar('PV').split('-l4t')[0].split('.') + ['0', '0'])[:3])}"
