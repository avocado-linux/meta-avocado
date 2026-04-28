# meta-synaptics installs /etc/docker/daemon.json (target runtime config) via a
# hardcoded path that lands outside FILES for nativesdk builds. Strip it so the
# SDK host build doesn't fail the installed-vs-shipped QA check.
do_install:append:class-nativesdk() {
    rm -rf ${D}/etc
}
