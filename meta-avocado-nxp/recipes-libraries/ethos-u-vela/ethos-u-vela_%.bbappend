# Provide Vela in the SDK (x86_64) so Ethos-U models are compiled at build time.
# Avocado cross-compiles everything and exposes no host-tool path, and Vela ships
# only as an sdist with a C extension (mlw_codec) -- so build it properly as a
# nativesdk package (cross-built for the SDK host via gcc-crosssdk) rather than
# pip-installing it into the cross SDK. Vela's deps (python3-numpy, python3-lxml,
# flatbuffers) already nativesdk-extend; python3-flatbuffers gets a matching
# bbappend.
BBCLASSEXTEND += "nativesdk"

# The base recipe gates COMPATIBLE_MACHINE = "(mx93-nxp-bsp)" (the TARGET Vela is
# i.MX93-only). nativesdk is machine-independent and clears the machine
# overrides, so that gate would (wrongly) skip the nativesdk variant. Lift it for
# nativesdk only -- the target variant stays mx93-gated. Which i.MX93 images
# actually pull nativesdk-ethos-u-vela is decided by the gated request in
# kas/vendor/nxp.yml (SDK_PKG_EXTRA_INSTALL:append:mx93-nxp-bsp), not here.
COMPATIBLE_MACHINE:class-nativesdk = "(.*)"
