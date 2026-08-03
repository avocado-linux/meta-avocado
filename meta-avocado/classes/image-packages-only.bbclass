# packages-only.bbclass
#
# Class for recipes where only packages are desired, without producing any image output
# This disables all image generation tasks while preserving package building

inherit image

# Disable image generation tasks
do_rootfs[noexec] = "1"
do_rootfs_wicenv[noexec] = "1"
do_image[noexec] = "1"
do_image_wic[noexec] = "1"
do_image_complete[noexec] = "1"

# Disable all SPDX/SBOM generation tasks
do_create_rootfs_spdx[noexec] = "1"
do_create_image_spdx[noexec] = "1"
do_create_image_spdx_setscene[noexec] = "1"
do_create_rootfs_spdx_setscene[noexec] = "1"
do_create_image_sbom_spdx[noexec] = "1"

# Disable image-specific settings
IMAGE_FSTYPES = ""
IMAGE_FEATURES = ""

# Ensure these recipes are excluded from world builds
EXCLUDE_FROM_WORLD = "1"

# --- Force dynamic out-of-tree package providers into the feed ---------------
#
# do_rootfs[noexec] above suppresses the dynamic runtime-provider resolution a
# real do_rootfs performs. Static providers in the image's runtime closure are
# still pulled in via do_rootfs[recrdeptask] (this is why e.g. efibootmgr, a plain
# RDEPENDS of a PKG_EXTRA_INSTALL packagegroup, still builds), but a *dynamic*
# PACKAGES_DYNAMIC provider that lives in its own out-of-tree recipe -- e.g.
# kernel-module-nvidia, produced by nvidia-gpu-modules via `inherit module` -- is
# never added to the build graph. Its RPMs never reach DEPLOY_DIR_RPM, so the
# packagegroup metadata RPM (carrying the Requires) lands in the feed while the
# modules it needs do not, and `avocado install` later fails with "nothing
# provides kernel-module-...".
#
# Any packages-only image that (transitively) pulls such a provider lists the
# provider recipe(s) in IMAGE_PACKAGES_ONLY_FORCE_PROVIDERS -- typically set in
# the machine/vendor conf next to the PKG_EXTRA_INSTALL that adds the packagegroup.
# The class turns each into a hard build+deploy dependency of do_build. do_build
# is deliberately chosen over the packagegroup's own do_package_write_rpm: it is
# never sstate/setscene-covered, so a shared-sstate build that restores the
# packagegroup from setscene cannot prune the dependency, and the provider is
# always built or setscene-restored (either path deploys its RPMs into
# DEPLOY_DIR_RPM, which is what the feed index scans).
IMAGE_PACKAGES_ONLY_FORCE_PROVIDERS ??= ""

python () {
    providers = (d.getVar('IMAGE_PACKAGES_ONLY_FORCE_PROVIDERS') or '').split()
    if providers:
        deps = ' '.join('%s:do_package_write_rpm' % p for p in providers)
        d.appendVarFlag('do_build', 'depends', ' ' + deps)
}
