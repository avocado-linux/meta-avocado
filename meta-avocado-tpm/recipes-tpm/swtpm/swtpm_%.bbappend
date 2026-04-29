# Avocado-side overrides on top of upstream meta-security's swtpm recipe.
# We need a fully-static native build of swtpm (so `swtpm` runs from
# the SDK without depending on host shared libs), which means: pull in
# extra native libs as DEPENDS, and pass `--disable-shared --enable-static`
# at configure time.
#
# Wrynose: dropped the local copy of `swtpm_0.10.0.bb`. Upstream
# meta-security ships the same version unmodified — we now bbappend
# instead of carrying the recipe.

DEPENDS:append = " libpcre-native"
DEPENDS:class-native = "libpcre-native libtasn1-native glib-2.0-native libtpms-native json-glib-native coreutils-native expect-native socat-native net-tools-native openssl-native gnutls-native fuse-native"

# Force native library discovery for native builds
EXTRA_OECONF:class-native += "--disable-shared --enable-static"
