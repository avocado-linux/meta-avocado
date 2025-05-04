DESCRIPTION = "Packagegroup for inclusion in Avocado NXP i.MX SDKs"
LICENSE = "Apache-2.0"

inherit packagegroup

RDEPENDS:${PN} = " \
  nativesdk-uuu \
"
