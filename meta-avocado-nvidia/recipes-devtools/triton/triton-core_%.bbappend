PACKAGECONFIG = "logging gpu metrics metrics_cpu stats ensemble"
DEPENDS:append = " grpc prometheus-cpp"

EXTRA_OECMAKE:append = " \
  -DTRITON_VERSION=${PV} \
"
SRC_URI = "\
    git:///avocado-build/git-dev/triton-inference-server/core;protocol=file;branch=avocado \
"
SRCREV = "${AUTOREV}"
