SUMMARY = "Builds the Avocado SDK for the platform"
LICENSE = "Apache-2.0"

inherit image packages-only

EXCLUDE_FROM_WORLD = "1"

IMAGE_INSTALL = "packagegroup-avocado-sdk"

DEPENDS += "packagegroup-core-standalone-sdk-target target-sdk-provides-dummy"
