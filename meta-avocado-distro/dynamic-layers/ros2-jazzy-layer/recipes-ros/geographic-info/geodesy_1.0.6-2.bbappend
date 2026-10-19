# package.xml says "BSD", which is neither an SPDX identifier nor a common-licence
# file, so do_create_spdx and do_populate_lic cannot find a text for it. The
# release repository ships no licence file for this package, so the clause count
# could not be read from a licence text. Treat "BSD" as
# BSD-3-Clause, the licence the ROS ecosystem means by it. This is an assumption
# for the feed build, not something verified against the upstream licence.
# LIC_FILES_CHKSUM is unchanged. Pinned to the recipe version so a layer bump
# brings the override up for removal.
LICENSE = "BSD-3-Clause"
