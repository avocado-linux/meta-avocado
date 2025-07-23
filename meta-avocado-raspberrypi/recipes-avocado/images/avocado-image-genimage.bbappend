do_genimage[depends] += "u-boot:do_deploy"
do_genimage[depends] += "rpi-bootfiles:do_deploy"

# Base boot files list
GENIMAGE_VARIABLES[BOOT-FILES] += "\
  'avocado-image-initramfs-${MACHINE}.cpio.zst',\
  'Image',\
  'bootcode.bin',\
  'cmdline.txt',\
  'config.txt',\
  'fixup_cd.dat',\
  'fixup_db.dat',\
  'fixup_x.dat',\
  'fixup.dat',\
  'fixup4.dat',\
  'fixup4cd.dat',\
  'fixup4db.dat',\
  'fixup4x.dat',\
  'start_cd.elf',\
  'start_db.elf',\
  'start_x.elf',\
  'start.elf',\
  'start4.elf',\
  'start4cd.elf',\
  'start4db.elf',\
  'start4x.elf',\
"

# Task to dynamically add bcm*.dtb* files to BOOT-FILES
python do_add_kernel_devicetree() {
    import os
    import bb

    bb.note("=== Starting prepare_genimage task ===")

    # Get the current BOOT-FILES value
    boot_files_str = d.getVarFlag('GENIMAGE_VARIABLES', 'BOOT-FILES')
    bb.note(f"Current BOOT-FILES value: {boot_files_str}")

    # Parse the existing boot files (or start with empty list if not set)
    boot_files = []
    if boot_files_str:
        for line in boot_files_str.split('\n'):
            line = line.strip()
            if line.startswith("'") and line.endswith("',"):
                boot_files.append(line[:-1])  # Remove trailing comma
            elif line.startswith("'") and line.endswith("'"):
                boot_files.append(line)

    bb.note(f"Parsed {len(boot_files)} existing boot files")

    # Get the deploy directory
    deploy_dir = d.getVar('DEPLOY_DIR_IMAGE')
    bb.note(f"DEPLOY_DIR_IMAGE: {deploy_dir}")

    # Get the RPI_KERNEL_DEVICETREE variable
    rpi_dtb_list = d.getVar('RPI_KERNEL_DEVICETREE')
    if rpi_dtb_list:
        bb.note(f"RPI_KERNEL_DEVICETREE: {rpi_dtb_list}")
        for dtb_file in rpi_dtb_list.split():
            dtb_basename = os.path.basename(dtb_file)
            dtb_deployed = os.path.join(deploy_dir, dtb_basename)
            if os.path.exists(dtb_deployed):
                if f"'{dtb_basename}'" not in boot_files:
                    boot_files.append(f"'{dtb_basename}'")
                    bb.note(f"Added DTB file to boot files: {dtb_basename}")
                else:
                    bb.note(f"DTB file already in boot files: {dtb_basename}")
            else:
                bb.note(f"DTB file not found in deploy dir: {dtb_deployed}")
    else:
        bb.warn("RPI_KERNEL_DEVICETREE is not set or empty")

    # Convert the list back to the required format
    boot_files_str = ", ".join(boot_files)
    bb.note(f"Final BOOT-FILES value: {boot_files_str}")

    # Set the variable
    d.setVarFlag('GENIMAGE_VARIABLES', 'BOOT-FILES', boot_files_str)
    bb.note("=== Finished prepare_genimage task ===")
}

do_genimage[prefuncs] = "do_add_kernel_devicetree do_genimage_preprocess"
do_add_kernel_devicetree[depends] += "virtual/kernel:do_deploy"
