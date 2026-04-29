DESCRIPTION = "Packagegroup for extra packages in Avocado NXP i.MX SDKs"
LICENSE = "Apache-2.0"

inherit packagegroup nospdx

RDEPENDS:${PN} = " \
  nativesdk-uuu \
"
