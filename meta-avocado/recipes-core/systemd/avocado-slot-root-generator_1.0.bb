SUMMARY = "Resolve the A/B rootfs slot from the booted ESP in the initramfs"
DESCRIPTION = "A systemd generator that reads the LoaderDevicePartUUID EFI \
variable and retargets sysroot.mount at the rootfs slot belonging to the ESP \
the firmware booted, so that one boot image works from either slot."
LICENSE = "Apache-2.0"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/Apache-2.0;md5=89aea4e17d99a7cacdbeed46a0096b10"

FILESEXTRAPATHS:prepend := "${THISDIR}/files:"

# stone.bbclass puts every layer's stone/ directory on FILESPATH, which is what
# lets the machine's manifest - the file that assigns the ESP partition UUIDs -
# be a SRC_URI entry here. Building the runtime table from that same file is
# the point of the inherit: a table transcribed into this recipe would be a
# second home for those UUIDs and a silent way for the two to drift apart.
inherit stone

# Skip the recipe outright on machines that do not boot UEFI, mirroring the
# condition packagegroup-avocado-initramfs.bb uses to pull it in - so recipe
# availability and recipe consumption cannot drift apart.
#
# This has to be a parse-time skip, not a task-time check. The SRC_URI below
# names the machine's stone manifest, and base.bbclass wires
# do_fetch[file-checksums] to bb.fetch.get_checksum_file_list(d), which fatals
# on a file:// entry it cannot resolve. That varflag expands during taskhash
# computation, after parsing - so `bitbake -p` fails for any machine with no
# stone manifest at all, which is every container-SDK build. do_write_slot_map's
# own guards below cannot help: a task never runs on a recipe whose parse
# already died.
#
# Gating on AVOCADO_BOOTLOADER rather than on whether the manifest happens to
# exist is deliberate. A UEFI machine that is genuinely missing its manifest
# should still hit the checksum error, which names every path it searched and so
# says exactly which file to add; silently skipping the recipe there would
# instead surface as an unrelated "nothing RPROVIDES" failure from the
# packagegroup.
python __anonymous() {
    if not bb.utils.contains("AVOCADO_BOOTLOADER", "uefi", True, False, d):
        raise bb.parse.SkipRecipe(
            "AVOCADO_BOOTLOADER does not contain 'uefi'; the rootfs slot is "
            "resolved from the booted ESP and only applies to UEFI machines")
}

SRC_URI = "file://avocado-slot-root-generator \
           file://stone-${MACHINE_SHORT_NAME}.json"

# Only file:// fetches, and wrynose no longer auto-creates ${S}.
S = "${UNPACKDIR}"

PACKAGE_ARCH = "${MACHINE_ARCH}"

python do_write_slot_map() {
    import json
    import os

    machine = d.getVar("MACHINE_SHORT_NAME")
    manifest_path = os.path.join(d.getVar("UNPACKDIR"), "stone-%s.json" % machine)

    with open(manifest_path) as handle:
        manifest = json.load(handle)

    update = manifest.get("update") or {}
    detection = update.get("slot_detection") or {}

    # Every other slot_detection type answers "which slot am I on?" from
    # somewhere this generator does not read - a U-Boot variable, a command.
    # Installing it anyway would ship a generator that silently never fires, so
    # refuse at build time instead and make whoever adds such a machine choose.
    if detection.get("type") != "sdboot-efi":
        bb.fatal("stone-%s.json declares slot_detection type %r, but "
                 "avocado-slot-root-generator resolves the slot from the "
                 "booted ESP and only works with sdboot-efi"
                 % (machine, detection.get("type")))

    rootfs = (update.get("os_artifacts") or {}).get("rootfs") or {}
    slot_partitions = rootfs.get("slot_partitions") or []

    # stone indexes slot_partitions positionally by slot, in the order its
    # update strategy defines - a then b for sdboot-ab. Reading the pairing off
    # that index rather than off the "rootfs-<letter>" spelling keeps this
    # working if a manifest ever names its partitions something else.
    slot_names = dict(zip(["a", "b"], slot_partitions))

    lines = ["# Generated from stone-%s.json. Do not edit.\n" % machine,
             "# <ESP partition UUID (LoaderDevicePartUUID)> <rootfs partition label>\n"]

    for uuid, slot in sorted(detection.get("partitions", {}).items()):
        partition = slot_names.get(slot)
        if not partition:
            bb.fatal("stone-%s.json maps ESP %s to slot %r, but "
                     "update.os_artifacts.rootfs.slot_partitions has no "
                     "partition for that slot: %r"
                     % (machine, uuid, slot, slot_partitions))
        lines.append("%s %s\n" % (uuid.lower(), partition))

    if len(lines) == 2:
        bb.fatal("stone-%s.json declares sdboot-efi slot detection with no "
                 "partitions; there is no slot for the generator to resolve"
                 % machine)

    with open(os.path.join(d.getVar("S"), "slot-root-map"), "w") as handle:
        handle.writelines(lines)
}
addtask write_slot_map after do_patch before do_install

do_install() {
    install -d ${D}${systemd_unitdir}/system-generators
    install -m 0755 ${S}/avocado-slot-root-generator \
        ${D}${systemd_unitdir}/system-generators/avocado-slot-root-generator

    install -d ${D}${nonarch_libdir}/avocado
    install -m 0644 ${S}/slot-root-map ${D}${nonarch_libdir}/avocado/slot-root-map
}

FILES:${PN} = "${systemd_unitdir}/system-generators/avocado-slot-root-generator \
               ${nonarch_libdir}/avocado/slot-root-map"

RDEPENDS:${PN} = "systemd"
