# Shared by the linux-yocto family on Jetson: linux-yocto (default mc) and
# linux-yocto-rt (jetson-rt mc). Both build the same 6.18 yocto-kernel tree off
# different KBRANCHes, so they share a files directory and the same patch queue.

require recipes-kernel/linux/avocado-linux-tegra.inc

FILESEXTRAPATHS:prepend := "${THISDIR}/linux-yocto-6.18:${THISDIR}/files:"

# spi-tegra114 drops a software-held chip select on the next spi_message, which
# breaks any driver that builds one transaction out of several messages with
# cs_change (tpm_tis_spi, cros_ec_spi, mmc_spi, ad_sigma_delta, ...). On Thor
# this is why a discrete SPI TPM never binds: the TIS data phase reads back as
# zeros and tpm_tis_core_init() gives up with -ENODEV before tpm_chip_start().
# See the patch header for the userspace reproduction that isolates it from the
# TPM driver.
#
# Needed by the RT sibling for the same reason: same driver, same tree, and the
# RT branch carries no fix of its own.
SRC_URI += " file://0001-spi-tegra114-keep-software-CS-across-a-multi-message-.patch"
