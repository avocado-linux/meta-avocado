SUMMARY = "NVIDIA GPU System Processor (GSP) firmware"
DESCRIPTION = "GSP firmware files required by NVIDIA driver 530+ for Turing and \
later GPUs. The GSP firmware runs on the GPU's system processor and handles \
initialization and management tasks. Required for RTX 20/30/40/50 series GPUs."
HOMEPAGE = "https://www.nvidia.com/drivers/"

require nvidia-gpu-userspace.inc

do_configure[noexec] = "1"
do_compile[noexec] = "1"

do_install() {
    install -d ${D}${nonarch_base_libdir}/firmware/nvidia/${PV}

    # Install all GSP firmware files from the firmware/ directory.
    # Typical files:
    #   gsp_ga10x.bin -- Ada Lovelace (RTX 40) and Ampere (RTX 30)
    #   gsp_tu10x.bin -- Turing (RTX 20)
    # Additional firmware files may be present for newer GPU architectures.
    for fw in ${S}/firmware/gsp*.bin; do
        if [ -f "${fw}" ]; then
            install -m 0644 "${fw}" ${D}${nonarch_base_libdir}/firmware/nvidia/${PV}/
        fi
    done
}

FILES:${PN} = "${nonarch_base_libdir}/firmware/nvidia/*"

# Firmware is not executable code -- skip irrelevant QA
INSANE_SKIP:${PN} = "arch"

# No dev/dbg packages needed for firmware
PACKAGES = "${PN}"
