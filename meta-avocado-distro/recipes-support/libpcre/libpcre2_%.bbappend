# Enable static library builds for qemu-user-static.
# libpcre2 uses autotools, so oe-core's no-static-libs.inc appends --disable-static
# and strips libpcre2-8.a. glib-2.0 needs it for static linking, so opt back in.
# qemu-user-static links --static and would otherwise fail with
# "ld: cannot find -lpcre2-8". (Ported from scarthgap; dropped during the wrynose
# migration when qemu-user-static was reauthored for QEMU 10.2.0.)
DISABLE_STATIC = ""
