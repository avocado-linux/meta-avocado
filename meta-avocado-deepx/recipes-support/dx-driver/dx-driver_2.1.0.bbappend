FILESEXTRAPATHS:prepend := "${THISDIR}/files:"

SRC_URI:append = " file://0001-dx_dma-fix-sleeping-in-atomic-BUG-in-dw_edma_free_de.patch;striplevel=2"
