LICENSE = "MIT"

inherit useradd

RDEPENDS:${PN} += "shadow"
ALLOW_EMPTY:${PN} = "1"

USERADD_PACKAGES = "${PN}"
USERADD_PARAM:${PN} = "--system --no-create-home --home-dir /var/run/sshd --shell /bin/false --user-group sshd"
