# package.xml says "BSD", which is neither an SPDX identifier nor a common-licence
# file, so do_create_spdx cannot find a text for it. The headers under
# include/eigen_stl_containers/ carry the Willow Garage licence, which has the
# three BSD clauses including the non-endorsement one. LIC_FILES_CHKSUM is
# unchanged, so the checksum still guards the line in package.xml.
# Pinned to the recipe version so a layer bump brings the override up for removal.
LICENSE = "BSD-3-Clause"
