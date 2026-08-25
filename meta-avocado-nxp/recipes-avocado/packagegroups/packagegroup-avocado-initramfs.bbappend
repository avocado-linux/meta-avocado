# imx-sdma probes in the initramfs and requests sdma-imx7d.bin there. With the
# firmware only in the rootfs, the direct load fails, the kernel falls back to
# the 60 s user-helper wait, and the whole boot carries that stall (observed on
# imx8mp-evk: "sdma or sdma firmware not ready" at 24 s, "firmware found" at
# 62 s, UART RX DMA given up in between). Ship the blob in the initramfs on the
# i.MX 8M family, which is where the SDMA lives; i.MX 9 uses eDMA.
RDEPENDS:${PN}:append:mx8m-generic-bsp = " firmware-imx-sdma-imx7d"
