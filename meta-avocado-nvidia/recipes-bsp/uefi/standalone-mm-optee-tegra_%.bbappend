# Compiles the same edk2 sources as edk2-firmware-tegra, for the S-EL0 secure
# partition that owns UEFI variable storage. It needs its own append because the
# edk2-firmware-tegra% glob cannot match a name starting standalone-mm-.
require edk2-cve.inc
