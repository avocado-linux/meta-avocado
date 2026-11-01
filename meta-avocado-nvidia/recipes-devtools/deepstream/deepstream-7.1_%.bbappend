# DeepStream 7.1's prebuilt plugins (e.g. libnvdsgst_nvmultiurisrcbin.so) link
# libjsoncpp.so.25, from jsoncpp 1.9.5; meta-oe scarthgap now ships 1.9.7.
# jsoncpp25 provides that soname alongside the current jsoncpp.
DEPENDS += "jsoncpp25"
RDEPENDS:${PN} += "jsoncpp25"
