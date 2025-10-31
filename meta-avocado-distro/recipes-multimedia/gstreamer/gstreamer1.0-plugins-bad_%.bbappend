EXTRA_OEMESON += "-Dfdkaac=enabled"
DEPENDS:append = " fdk-aac"
RDEPENDS:${PN}:append = " fdk-aac"

PACKAGECONFIG:append = " openh264"
