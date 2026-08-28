# Drop one of meta-qcom's three freedreno backports: oe-core's mesa already has it.
#
# meta-qcom's mesa.bbappend adds all three unconditionally for :qcom, with no
# version guard. Against oe-core's mesa 26.1.0 the UBWC one is already upstream,
# so quilt refuses it and takes the whole do_patch down -- which fails every
# build that pulls graphics (i.e. everything, once kas/feature/complete.yml is
# stacked):
#
#   Hunk #1 FAILED at 34. ... 2 out of 2 hunks FAILED
#   Patch 0001-freedreno-layout-tu-Fix-UBWC-block-sizes-for-PIPE_FO.patch
#     can be reverse-applied
#
# The patch says so itself -- Upstream-Status: Backport [mesa fb2646e527e9] --
# and 26.1.0 carries it: src/freedreno/fdl/fd6_layout.c already tests
# layout->format == PIPE_FORMAT_R8_G8B8_420_UNORM against layout->plane.
#
# Only this one. Dry-running all three against the 26.1.0 tarball:
#   0001-freedreno-Add-support-for-A704.patch                  applies -> keep
#   0001-freedreno-Modify-reg_size_vec4-for-a608-and-a612-...  applies -> keep
#   0001-freedreno-layout-tu-Fix-UBWC-block-sizes-...          reverse-applies
#
# Removed here rather than in the vendored layer: the real fix is a version
# guard upstream in meta-qcom, since the mismatch hits anyone pairing its
# wrynose branch with a newer oe-core. Revisit on the next meta-qcom repin --
# if upstream drops or guards the patch, this becomes a no-op and can go.
SRC_URI:remove = "file://0001-freedreno-layout-tu-Fix-UBWC-block-sizes-for-PIPE_FO.patch"
