FILESEXTRAPATHS:prepend := "${THISDIR}/files:"

# Avocado has no UDisks (it needs the polkit distro feature), so fwupd never
# finds the ESP and no UEFI capsule device is updatable. The patch makes the
# configured EspLocation the fallback; /boot is where Avocado's UEFI machines
# mount the ESP of the booted slot (systemd's ESP automount), which is also
# the one the firmware reads capsule-on-disk updates from. Machines without
# an ESP at /boot are unaffected: the fallback requires an EFI directory.
SRC_URI += "file://0001-context-use-EspLocation-when-UDisks-finds-no-ESP.patch"

do_install:append() {
    sed -i '/^\[fwupd\]$/a EspLocation=/boot' ${D}${sysconfdir}/fwupd/fwupd.conf
    grep -q '^EspLocation=/boot$' ${D}${sysconfdir}/fwupd/fwupd.conf
}

# With the ptest distro feature fwupd's tests are on, and meson setup runs the
# gcab fwupd just built for the target. Without qemu-usermode (x86-64-v4: QEMU
# cannot run AVX-512) meson has no exe_wrapper and setup fails, so build those
# machines without the tests; their ptests could not run under QEMU anyway.
PACKAGECONFIG:remove = "${@bb.utils.contains('MACHINE_FEATURES', 'qemu-usermode', '', 'tests', d)}"
