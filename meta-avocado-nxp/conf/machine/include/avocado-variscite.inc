# Deltas shared by every Avocado machine built on Variscite's BSP layers
# (meta-variscite-bsp-imx + -common, vendored via kas/vendor/variscite.yml).
# Required by the avocado-*-var-* machine confs; anything SoC-specific
# (KERNEL_IMAGETYPE's override family, device trees, boot addresses) stays in
# the machine conf.

# Use the NXP-BSP Variscite kernel (linux-imx-based). variscite.inc only sets
# this as a ?= default, and imx-base.inc has its own; assign it outright so the
# kernel matches the NXP-BSP userspace the shared i.MX packagegroups are
# version-matched to (Vivante/Mali GL + Wayland, and the NPU stacks).
PREFERRED_PROVIDER_virtual/kernel = "linux-variscite-imx"

# packagegroup-avocado-imx-extra pulls the NXP 88W8997 wlan driver/firmware,
# which no Variscite SOM uses -- their WiFi/BT is the NXP IW612 via the
# nxpiw612-sdio MACHINE_FEATURE + iw612-utils, set by the vendor machine confs.
# Drop it and substitute the Variscite variant. The append being removed is
# injected by kas/vendor/{freescale,nxp}.yml.
PKG_EXTRA_INSTALL:remove = "packagegroup-avocado-imx-extra"
PKG_EXTRA_INSTALL:append = " packagegroup-avocado-variscite-extra"

# meta-variscite-bsp-imx's systemd bbappend (gated on imx-generic-bsp, present
# on every i.MX board) adds its own 0001-units-add-dependencies / 0002-disable-
# networkd-wait-online patches, written for the Variscite BSP's older systemd.
# They fail to apply to Avocado's systemd 258.1 (do_patch reject on
# units/systemd-networkd.service.in). Both are connman / NetworkManager-vs-
# networkd coexistence tweaks, irrelevant to Avocado's networkd-only setup, so
# drop the whole bbappend rather than carry a refreshed vendor patch. BBMASK
# here is parsed only for Variscite MACHINEs, so it stays scoped to them. (The
# separate systemd-serialgetty.bbappend, which disables the debug getty, is
# intact.)
BBMASK += "meta-variscite-bsp-imx/recipes-core/systemd/systemd_%.bbappend"

# Every Variscite SOM Avocado targets carries a Cortex-M co-processor (M7 on
# the i.MX8MP and i.MX95 DARTs); advertise it so the shared SDK packagegroup
# pulls in the bare-metal ARM toolchain (via kas/vendor/arm.yml, included
# transitively through kas/vendor/nxp.yml).
MACHINE_FEATURES:append = " cortex-m"
