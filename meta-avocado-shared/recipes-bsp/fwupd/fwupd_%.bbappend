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
