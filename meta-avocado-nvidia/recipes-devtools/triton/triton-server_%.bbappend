PACKAGECONFIG = "logging http gpu tensorrt metrics metrics_cpu stats ensemble"
DEPENDS:append = " civetweb"

EXTRA_OECMAKE:append = " \
  -DTRITON_VERSION=${PV} \
"

SRC_URI = "git:///avocado-build/git-dev/triton-inference-server/server;protocol=file;branch=avocado"
SRCREV = "${AUTOREV}"
