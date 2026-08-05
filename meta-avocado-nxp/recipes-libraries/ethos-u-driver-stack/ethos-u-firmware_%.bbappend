# The i.MX93 FRDM carries the same 11x11 LPDDR4x i.MX93 SoC as the
# imx93-11x11-lpddr4x-evk, so it uses the EVK's Ethos-U65 firmware build rather
# than the recipe's generic default. The vendor recipe (meta-imx-ml) maps only
# the EVK/QSB variants; add the FRDM mapping here. A bbappend parses after the
# recipe, so this override wins over the recipe's strong ETHOS_U_FIRMWARE
# assignment.
ETHOS_U_FIRMWARE:imx93-11x11-lpddr4x-frdm = "ethosu_firmware_11x11"
