#!/bin/sh
# Point /run/nvpmodel.conf at the power model for the P3767 module (Orin NX /
# Orin Nano) this image booted on. /etc/nvpmodel.conf is a symlink to it.
#
# One image boots every P3767 SKU, so the conf cannot be chosen at build time.
# The table is the p3767 part of create_nvpmodel_symlink() in NVIDIA's
# nvpower.sh, which meta-tegra patches out because it writes to /etc. It keys
# on the device-tree compatible, which also tells super and non-super DTBs
# apart; their power tables differ.

nvpmodel_conf_for() {
  case "$1" in
    *p3767-0000-as-p3767-0001*) echo nvpmodel_p3767_0001 ;;
    *p3767-0000-as-p3767-0003*) echo nvpmodel_p3767_0003 ;;
    *p3767-0000-as-p3767-0004*) echo nvpmodel_p3767_0004 ;;
    *p3767-0000-super*) echo nvpmodel_p3767_0000_super ;;
    *p3767-0001-super*) echo nvpmodel_p3767_0001_super ;;
    *p3767-0001*) echo nvpmodel_p3767_0001 ;;
    *p3767-0002*) echo nvpmodel_p3767_0000 ;;
    *p3767-0003-super* | *p3767-0005-super*) echo nvpmodel_p3767_0003_super ;;
    *p3767-0003* | *p3767-0005*) echo nvpmodel_p3767_0003 ;;
    *p3767-0004-super*) echo nvpmodel_p3767_0004_super ;;
    *p3767-0004*) echo nvpmodel_p3767_0004 ;;
    *p3767*) echo nvpmodel_p3767_0000 ;;
  esac
}

compat=$(tr -d '\0' </proc/device-tree/compatible)
conf=/etc/nvpmodel/$(nvpmodel_conf_for "$compat").conf
if [ ! -f "$conf" ]; then
  echo "nvpmodel-select: no conf for '$compat', using @NVPMODEL@" >&2
  conf=/etc/nvpmodel/@NVPMODEL@.conf
fi
ln -sfn "$conf" /run/nvpmodel.conf
echo "nvpmodel-select: /etc/nvpmodel.conf -> $conf"
