FILESEXTRAPATHS:prepend := "${THISDIR}/${PN}:"

PACKAGECONFIG = "logging gpu metrics metrics_cpu stats ensemble"
DEPENDS:append = " prometheus-cpp"

EXTRA_OECMAKE:append = " \
  -DTRITON_VERSION=${PV} \
"
SRC_URI = "\
    git://github.com/triton-inference-server/core.git;protocol=https;branch=r24.12 \
    file://0001-Build-fixups.patch \
"
