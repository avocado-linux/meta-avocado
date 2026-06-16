# pango's gobject-introspection step runs g-ir-scanner, which compiles the
# introspection probe binary through distutils. That path invokes the compiler
# as the bare `ccache` argv[0] and fails do_compile with
# "command '.../ccache' failed with exit code 1" - g-ir-scanner's dumper does
# not tolerate the ccache wrapper. Disable ccache for this recipe; the
# introspection compile is small, so the cache loss is negligible.
CCACHE_DISABLE = "1"
