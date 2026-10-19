# Global mold scope forces this recipe to rebuild from scratch (see the
# go-runtime bbappend in this same layer for the mechanism), re-tripping a
# fatal [buildpaths] QA check that sstate reuse normally skips re-running:
#
#   ERROR: QA Issue: File /usr/bin/wget.wget in package wget contains
#          reference to TMPDIR [buildpaths]
#   ERROR: QA Issue: File /usr/src/debug/wget/1.25.0/src/version.c in package
#          wget-src contains reference to TMPDIR [buildpaths]
#
# configure records the link command line for `wget --version`, and with mold
# that line carries -B${WORKDIR}/recipe-sysroot-native/mold-ld-wrappers. The
# string is only printed by --version and never used at run time. Neither
# package is changed by it beyond that text, so the check is skipped for the
# two packages that carry it.
INSANE_SKIP:${PN}:append = " buildpaths"
INSANE_SKIP:${PN}-src:append = " buildpaths"
