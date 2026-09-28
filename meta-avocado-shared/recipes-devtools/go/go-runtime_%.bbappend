# Global mold scope forces this recipe to rebuild from scratch (MOLD_MODE is
# read inside mold.bbclass's globally-inherited anonymous python function, so
# changing it changes every recipe's signature regardless of MOLD_EXCLUDED_PN
# membership), re-tripping a fatal [buildpaths] QA check that sstate reuse
# normally skips re-running:
#
#   ERROR: QA Issue: File /usr/lib/go/pkg/linux_amd64_dynlink/net.a in package
#          go-runtime-dev contains reference to TMPDIR [buildpaths]
#
# Upstream oe-core commit f7b05ebfdc ("go: fix buildpath issue for
# go-runtime") already added -trimpath to the -buildmode=shared install step
# and patches Go's cmd/go ldShared to clear GOROOT under -trimpath - that fix
# is already in this tree and covers libstd.so cleanly. It does not cover the
# per-package *.a archives (net.a, plugin.a, os/user.a, runtime/cgo.a, ...),
# which come from a different Go toolchain code path (per-package archiving,
# not linking) that patch never touched, and no further upstream fix exists
# for it as of 2026-09.
#
# This recipe already treats go-runtime-dev's static .a archives as a special
# case - INSANE_SKIP:${PN}-dev already skips staticdev/file-rdeps/arch with
# the comment "pre-built binaries for multiple architectures... required in
# -dev". Extending the same skip to buildpaths matches that existing
# rationale: go-runtime-dev is SDK-only tooling, never shipped in a
# production image.
INSANE_SKIP:go-runtime-dev:append = " buildpaths"
