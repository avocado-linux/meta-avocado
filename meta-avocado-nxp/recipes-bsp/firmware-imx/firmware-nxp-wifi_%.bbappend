# Fix duplicate nxpiw610-sdio in PACKAGES.
# The base recipe (meta-freescale) already adds it via PACKAGES =+,
# but meta-imx-bsp appends it again causing a QA error.
python () {
    packages = d.getVar('PACKAGES').split()
    seen = []
    for p in packages:
        if p not in seen:
            seen.append(p)
    d.setVar('PACKAGES', ' '.join(seen))
}
