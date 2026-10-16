# Shared by the linux-yocto family on Jetson: linux-yocto (default mc) and
# linux-yocto-rt (jetson-rt mc). Both build the same 6.18 yocto-kernel tree off
# different KBRANCHes, so they share a files directory and the same patch queue.

require recipes-kernel/linux/avocado-linux-tegra.inc

FILESEXTRAPATHS:prepend := "${THISDIR}/linux-yocto-6.18:${THISDIR}/files:"

# Drivers the L4T kernel ships that 6.18 lacks, as modules. 6.18-only, so it
# lives here rather than in avocado-linux-tegra.inc.
SRC_URI += " file://avocado-modules.cfg"

# The PHY drivers nvethernet needs while it probes have to be built in (see
# avocado-phy-builtin.cfg). The Tegra layer's jetson-devkit.cfg sets
# CONFIG_AQUANTIA_PHY=m and is applied after any plain SRC_URI fragment, so the
# fragment rides in a feature that is appended to KERNEL_FEATURES and applied
# after it.
SRC_URI += " file://avocado-phy-builtin.scc file://avocado-phy-builtin.cfg"
KERNEL_FEATURES:append:tegra = " avocado-phy-builtin.scc"

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

# NVIDIA's AQR113C wake commit (get_wol/set_wol) lands its two table lines in
# the AQR111B0 phy_driver entry once the Tegra patch series is applied, so the
# 10G port's PHY has no get_wol and ethtool reports "Supports Wake-on: d". The
# fix moves them to the AQR113C entry. It has to apply after that series, which
# the SRC_URI patches (queued first) cannot do, so it is kept as a .fixup file,
# which the kernel patch queue does not pick up, and applied after do_patch.
# Drop it when the series carries the hooks in the right entry.
#
# The second fixup masks the autoneg interrupt while the AQR113C wake is armed.
# Arming restarts autonegotiation, and the resulting link-up event drives the PHY
# interrupt, which the Jetson wires as a wake source, so the system woke a few
# seconds after it suspended. NVIDIA's 6.8 kernel masks it; the 6.18 port lost
# those lines. Applied in order: it expects the first fixup's tree.
SRC_URI += " file://aquantia-aqr113c-wol-hooks.fixup file://aquantia-aqr113c-wol-mask-aneg-irq.fixup"

do_patch:append() {
    for name in aquantia-aqr113c-wol-hooks aquantia-aqr113c-wol-mask-aneg-irq; do
        fix="${UNPACKDIR}/${name}.fixup"
        if patch -p1 -R --dry-run -s -d ${S} < "$fix" > /dev/null 2>&1; then
            bbnote "${name}.fixup is already applied"
        else
            patch -p1 -d ${S} < "$fix" || bbfatal "${name}.fixup does not apply; the Tegra patch series changed"
        fi
    done
}
