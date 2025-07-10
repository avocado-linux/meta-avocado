LICENSE = "MIT"

inherit useradd

USERADD_PACKAGES = "${PN}"
USERADD_PARAM:${PN} = "--system --no-create-home --home-dir /var/run/sshd --shell /bin/false --user-group sshd"

RDEPENDS:${PN} += "shadow"

ALLOW_EMPTY:${PN} = "1"
