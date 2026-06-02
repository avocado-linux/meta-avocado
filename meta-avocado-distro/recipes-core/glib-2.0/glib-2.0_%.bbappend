# Enable static library builds for qemu-user-static.
# glib-2.0 uses Meson, which defaults to shared-only, so set default_library=both
# to also build libglib-2.0.a. qemu-user-static links --static and would otherwise
# fail with "ld: cannot find -lglib-2.0". (Ported from scarthgap; dropped during the
# wrynose migration when qemu-user-static was reauthored for QEMU 10.2.0.)
EXTRA_OEMESON:append = " -Ddefault_library=both"
