do_install:append() {
    install -d ${D}/efi
    # Container Dev Mode (design D8/H4): provision the trust-store LOCATION only.
    # The per-project CA is delivered into the engine trust store at `up`, never
    # baked into the image.
    install -d ${D}${sysconfdir}/container-dev
}
