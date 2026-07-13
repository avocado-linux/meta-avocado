# cmake's bundled curl (cmcurl, forced on by CMAKE_USE_SYSTEM_LIBRARY_CURL=0)
# hardcodes USE_NGHTTP2 and USE_LIBIDN2 ON in its CMakeLists.txt, regardless
# of any -D override. Both would need cmake-native to DEPENDS on a native
# variant that closes back onto cmake-native itself:
#   - nghttp2 inherits cmake directly (cmake.bbclass unconditionally
#     prepends cmake-native to DEPENDS).
#   - libidn2 inherits gtk-doc, which needs python3-native, which needs
#     expat-native, which inherits cmake - same cycle, one hop further out.
# Disable both in the bundled curl instead; cmake-native has no need for
# HTTP/2 multiplexing or internationalized domain names.
FILESEXTRAPATHS:prepend := "${THISDIR}/${PN}:"

SRC_URI += "file://0001-cmcurl-disable-nghttp2-and-libidn2-for-native-bootstrap.patch"
