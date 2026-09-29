SUMMARY = "Re-index DEPLOY_DIR_RPM as a servable avocado feed"
DESCRIPTION = "Run after building individual packages (bitbake foo && bitbake avocado-feed-index). \
avocado-complete already does this when AVOCADO_FEED_INDEX is 1."
LICENSE = "Apache-2.0"

INHIBIT_DEFAULT_DEPS = "1"
PACKAGES = ""

inherit nopackages avocado-feed

deltask do_fetch
deltask do_unpack
deltask do_patch
deltask do_configure
deltask do_compile
deltask do_install
deltask do_populate_lic
deltask do_populate_sysroot

DEPENDS = "createrepo-c-native"

do_feed_index[nostamp] = "1"

python do_feed_index() {
    bb.build.exec_func('avocado_feed_index', d)
}
addtask do_feed_index after do_prepare_recipe_sysroot before do_build

EXCLUDE_FROM_WORLD = "1"
