# Enable static library builds for qemu-user-static, next to the same fix for
# glib-2.0 and libpcre2 in this directory: qemu-user-static links --static and
# would otherwise fail with "ld: cannot find -lz". (Ported from scarthgap;
# dropped during the wrynose migration when qemu-user-static was reauthored
# for QEMU 10.2.0.)
DISABLE_STATIC = ""
