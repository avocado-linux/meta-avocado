# Target qemu is in the image for qemu-guest-agent and qemu-user-static
# (packagegroup-avocado-extra), not to run GPU-accelerated guests. With opengl
# in DISTRO_FEATURES oe-core's qemu.inc enables virglrenderer, whose 1.2.0
# do_compile fails against the Vivante (imx-gpu-viv) GL stack the NXP-BSP
# i.MX8M boards use for virtual/egl - the i.MX93/91/95 boards, on mesa, build
# it fine. Scoped to the Vivante override for that reason; the mesa boards keep
# the default.
PACKAGECONFIG:remove:imxviv = "virglrenderer epoxy"
