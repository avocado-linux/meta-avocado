FILESEXTRAPATHS:prepend := "${THISDIR}/files:"

SRC_URI:append = " \
  file://avocado-core.cfg \
  file://avocado-extra.cfg \
"

# Disable git-SHA scmversion suffix on KERNEL_VERSION. Upstream's set_scmversion
# uses `git rev-parse --short HEAD`, whose abbreviation length depends on repo
# object count (shallow vs full clone) and is not hashed as a task vardep — so
# sstate reuse across environments can mix scmversions between kernel and OOT
# module builds, leaving shim RDEPENDS pointing at a kernel name that nothing
# provides. SRCREV is pinned in the recipe, so no version info is lost.
SCMVERSION = "n"
