# Enable static library builds for qemu-user-static
# glib-2.0 uses Meson, so we set default_library=both to build .a and .so
EXTRA_OEMESON:append = " -Ddefault_library=both"
