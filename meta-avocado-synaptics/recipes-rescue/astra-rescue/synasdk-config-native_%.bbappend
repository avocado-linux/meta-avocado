python __anonymous() {
    machine = d.getVar("GRINN_MACHINE")
    mapping = {
        "sl1620": "sl1620_emmc.pt",
        "sl1640": "sl1640_emmc.pt",
        "sl1680": "sl1680_emmc.pt",
        "grinn-astra-1680-ada": "sl1680_emmc.pt",
        "grinn-astra-1680-evb": "sl1680_emmc.pt",
        "grinn-astra-1680-sbc": "sl1680_emmc.pt",
    }

    pt_file = mapping.get(machine, "")
    d.setVar("EMMC_PT_FILE", pt_file)
}

