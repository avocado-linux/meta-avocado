# Global mold scope forces this recipe to rebuild from scratch (see the
# go-runtime bbappend in this same layer for the mechanism), re-tripping a
# fatal [buildpaths] QA check that sstate reuse normally skips re-running:
#
#   ERROR: QA Issue: File /usr/lib/gettext/ptest/tests/init-env in package
#          gettext-ptest contains reference to TMPDIR [buildpaths]
#
# init-env is copied verbatim from the build tree (gettext_1.0.bb's
# do_install_ptest), carrying an absolute path autoconf/automake bakes into
# the generated test harness script. The recipe already strips one known
# leaked string (`sed -i -e 's|${DEBUG_PREFIX_MAP}||g' .../init-env`), but not
# the general build-tree path, and no upstream fix exists for the remainder.
#
# gettext-ptest is test tooling, never shipped in a production image, so
# skipping buildpaths for it carries no runtime risk.
INSANE_SKIP:gettext-ptest:append = " buildpaths"
