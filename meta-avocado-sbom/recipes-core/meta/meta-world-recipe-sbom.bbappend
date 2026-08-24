# One CVE scan for the whole build.
#
# meta-world-recipe-sbom is OE-core's aggregate SPDX 3.0 document: its
# do_create_recipe_sbom depends on every world target, so one document
# describes everything the build produces. sbom-cve-check-recipe scans exactly
# one SBOM, so appending it here analyses the whole build in a single pass.
#
# The alternatives both cost more or cover less:
#
#   INHERIT += "sbom-cve-check-recipe"  scans every recipe's full dependency
#                                       closure, once per recipe
#   IMAGE_CLASSES += "sbom-cve-check"   scans one image, but avocado ships a
#                                       package feed that images, extensions
#                                       and sysexts are composed from, so an
#                                       image is a subset of what a user can
#                                       install
#
# Nothing triggers the scan on its own: the recipe pins do_build's deps to
# do_create_recipe_sbom alone, which this append deliberately leaves as it is.
# avocado-cve-report depends on the task, so the report is what drives it.
inherit sbom-cve-check-recipe
