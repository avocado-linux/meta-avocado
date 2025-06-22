FILESEXTRAPATHS:prepend := "${THISDIR}/${PN}:"

SRC_URI:append = " \
  file://0002-Fix-gRPC-build.patch \
  file://0003-refactor-protobuf-stringpiece_internal.patch \
"

PACKAGECONFIG = "logging http gpu grpc tensorrt metrics metrics_cpu stats ensemble"
DEPENDS:append = " civetweb"

PACKAGECONFIG[grpc] = "-DTRITON_ENABLE_GRPC=ON,-DTRITON_ENABLE_GRPC=OFF,grpc re2-native python3-pybind11 cuda-cudart protobuf-c"

EXTRA_OECMAKE:append = ' \
  -DTRITON_VERSION=${PV} \
'
