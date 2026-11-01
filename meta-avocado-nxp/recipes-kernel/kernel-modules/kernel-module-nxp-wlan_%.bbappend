# moal has no SDIO/PCIe device table, so udev never loads it. Upstream
# meta-freescale (wrynose) ships the autoload entry and the mod_para option
# that points moal at the per-chip firmware table; the scarthgap recipe has
# neither, so on the i.MX 93 FRDM the IW612 enumerates on SDIO and no wlan
# ever appears. Backport both.
KERNEL_MODULE_PROBECONF += "moal"
module_conf_moal = "options moal mod_para=nxp/wifi_mod_para.conf"
KERNEL_MODULE_AUTOLOAD += "moal"
