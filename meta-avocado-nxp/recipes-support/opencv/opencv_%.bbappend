# See meta-avocado-nxp/recipes-multimedia/gstreamer/gstreamer1.0_%.bbappend
# for rationale.
PACKAGE_ARCH = "${MACHINE_ARCH}"

# meta-imx turns on OpenCL for every imxgpu machine, which pulls
# virtual/libopencl1. That only resolves on Vivante parts (imx-gpu-viv) or
# under NXP's distro, which adds "opencl" to DISTRO_FEATURES so meta-oe's
# opencl-icd-loader becomes buildable. Avocado sets neither, and Mali parts
# (i.MX95) ship no OpenCL ICD here anyway, so drop it rather than build a
# loader with nothing behind it.
PACKAGECONFIG_OPENCL:imxmali = ""
