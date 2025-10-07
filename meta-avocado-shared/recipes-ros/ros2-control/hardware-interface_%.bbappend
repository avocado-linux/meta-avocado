FILESEXTRAPATHS:prepend := "${THISDIR}/${BPN}:"

SRC_URI:remove = "file://use-tinyxml-by-name.patch"
SRC_URI:remove = "file://remove-buildpath.patch"

SRC_URI:append = "\
  file://0001-Use-pkg-config-to-find-TinyXML2.patch \
  file://0002-Remove-buildpath.patch \
"
