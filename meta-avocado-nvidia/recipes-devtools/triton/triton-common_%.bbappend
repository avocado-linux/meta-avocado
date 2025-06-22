FILESEXTRAPATHS:prepend := "${THISDIR}/${PN}:"
PACKAGECONFIG = "protobuf grpc rapidjson"
DEPENDS += "grpc-native"

SRC_URI:append = " \
  file://0002-fix-protobuf-libupb.patch \
  file://0003-export-libraries.patch \
"
