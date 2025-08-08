inherit stone

do_compile[depends] += "u-boot:do_deploy"

DEPENDS += " jq-native mkfat-native fwup-native"

SRC_URI += "file://${MACHINE_SHORT_NAME}/rootdisk.conf"

do_deploy:append() {
  install -d ${DEPLOYDIR}
  install -m 0644 ${WORKDIR}/${MACHINE_SHORT_NAME}/rootdisk.conf ${DEPLOYDIR}/rootdisk.conf
}

do_stone_provision:append() {
  convert_unit_to_bytes() {
    value="$1"
    unit="$2"

    case "$unit" in
      "bytes")
          echo "$value"
          ;;
      "kibibytes")
          echo $(expr "$value" \* 1024)
          ;;
      "mebibytes")
          echo $(expr "$value" \* 1024 \* 1024)
          ;;
      *)
          echo "Error: unsupported unit: $unit" >&2
          return 1
          ;;
    esac
  }

  stone_manifest="${DEPLOY_DIR_IMAGE}/stone-${MACHINE_SHORT_NAME}.json"
  rootdisk_config=$(cat "${stone_manifest}" | jq .storage_devices.rootdisk)
  images_config=$(echo "${rootdisk_config}" | jq .images)
  architecture=$(cat "${stone_manifest}" | jq -r .runtime.architecture)
  disk_uuid=$(echo "${rootdisk_config}" | jq -r .uuid)
  boot_config=$(echo "${images_config}" | jq .boot)
  boot_size=$(echo "${boot_config}" | jq -r .size)
  boot_image_file=$(echo "${boot_config}" | jq -r .out)
  echo "${boot_config}" | mkfat -b "${DEPLOY_DIR_IMAGE}" -s "${boot_size}" -o "${DEPLOY_DIR_IMAGE}/${boot_image_file}"

  partitions_config=$(echo "${rootdisk_config}" | jq .partitions)
  uboot_env_partition=$(echo "${partitions_config}" | jq -r '.[] | select(.name == "uboot-env")')
  boot_a_partition=$(echo "${partitions_config}" | jq -r '.[] | select(.name == "boot-a")')
  boot_b_partition=$(echo "${partitions_config}" | jq -r '.[] | select(.name == "boot-b")')
  rootfs_a_partition=$(echo "${partitions_config}" | jq -r '.[] | select(.name == "rootfs-a")')
  rootfs_b_partition=$(echo "${partitions_config}" | jq -r '.[] | select(.name == "rootfs-b")')
  var_partition=$(echo "${partitions_config}" | jq -r '.[] | select(.name == "var")')

  block_size=$(echo "${rootdisk_config}" | jq -r .block_size)

  uboot_env_offset_val=$(echo "${uboot_env_partition}" | jq -r .offset)
  uboot_env_offset_unit=$(echo "${uboot_env_partition}" | jq -r .offset_unit)
  offset_in_bytes=$(convert_unit_to_bytes "$uboot_env_offset_val" "$uboot_env_offset_unit")
  uboot_env_offset_blocks=$(expr "$offset_in_bytes" / "$block_size")

  uboot_env_offset_redund_val=$(echo "${uboot_env_partition}" | jq -r .offset_redundant)
  uboot_env_offset_redund_unit=$(echo "${uboot_env_partition}" | jq -r .offset_redundant_unit)
  offset_redund_in_bytes=$(convert_unit_to_bytes "$uboot_env_offset_redund_val" "$uboot_env_offset_redund_unit")
  uboot_env_offset_redund_blocks=$(expr "$offset_redund_in_bytes" / "$block_size")

  uboot_env_size_val=$(echo "${uboot_env_partition}" | jq -r .size)
  uboot_env_size_unit=$(echo "${uboot_env_partition}" | jq -r .size_unit)
  size_in_bytes=$(convert_unit_to_bytes "$uboot_env_size_val" "$uboot_env_size_unit")
  uboot_env_size_blocks=$(expr "$size_in_bytes" / "$block_size")

  uboot_env_image_name=$(echo "${uboot_env_partition}" | jq -r .image)
  uboot_env_image_file=$(echo "${images_config}" | jq -r --arg key "${uboot_env_image_name}" '.[$key] | if type=="object" then .out else . end')

  rootfs_a_image_name=$(echo "${rootfs_a_partition}" | jq -r .image)
  rootfs_a_image_file=$(echo "${images_config}" | jq -r --arg key "${rootfs_a_image_name}" '.[$key] | if type=="object" then .out else . end')
  var_image_name=$(echo "${var_partition}" | jq -r .image)
  var_image_file=$(echo "${images_config}" | jq -r --arg key "${var_image_name}" '.[$key] | if type=="object" then .out else . end')

  boot_a_offset_val=$(echo "${boot_a_partition}" | jq -r .offset)
  boot_a_offset_unit=$(echo "${boot_a_partition}" | jq -r .offset_unit)
  boot_a_offset_in_bytes=$(convert_unit_to_bytes "$boot_a_offset_val" "$boot_a_offset_unit")
  boot_a_offset_blocks=$(expr "$boot_a_offset_in_bytes" / "$block_size")

  boot_a_size_val=$(echo "${boot_a_partition}" | jq -r .size)
  boot_a_size_unit=$(echo "${boot_a_partition}" | jq -r .size_unit)
  boot_a_size_in_bytes=$(convert_unit_to_bytes "$boot_a_size_val" "$boot_a_size_unit")
  boot_a_size_blocks=$(expr "$boot_a_size_in_bytes" / "$block_size")

  boot_b_offset_val=$(echo "${boot_b_partition}" | jq -r .offset)
  if [ -z "$boot_b_offset_val" ] || [ "$boot_b_offset_val" = "null" ]; then
      boot_b_offset_blocks=$(expr "$boot_a_offset_blocks" + "$boot_a_size_blocks")
  else
      boot_b_offset_unit=$(echo "${boot_b_partition}" | jq -r .offset_unit)
      boot_b_offset_in_bytes=$(convert_unit_to_bytes "$boot_b_offset_val" "$boot_b_offset_unit")
      boot_b_offset_blocks=$(expr "$boot_b_offset_in_bytes" / "$block_size")
  fi

  boot_b_size_val=$(echo "${boot_b_partition}" | jq -r .size)
  boot_b_size_unit=$(echo "${boot_b_partition}" | jq -r .size_unit)
  boot_b_size_in_bytes=$(convert_unit_to_bytes "$boot_b_size_val" "$boot_b_size_unit")
  boot_b_size_blocks=$(expr "$boot_b_size_in_bytes" / "$block_size")

  recovery_partition=$(echo "${partitions_config}" | jq -r '.[] | select(.name == "recovery")')
  recovery_offset_val=$(echo "${recovery_partition}" | jq -r .offset)
  if [ -z "$recovery_offset_val" ] || [ "$recovery_offset_val" = "null" ]; then
      recovery_offset_blocks=$(expr "$boot_b_offset_blocks" + "$boot_b_size_blocks")
  else
      recovery_offset_unit=$(echo "${recovery_partition}" | jq -r .offset_unit)
      recovery_offset_in_bytes=$(convert_unit_to_bytes "$recovery_offset_val" "$recovery_offset_unit")
      recovery_offset_blocks=$(expr "$recovery_offset_in_bytes" / "$block_size")
  fi

  recovery_size_val=$(echo "${recovery_partition}" | jq -r .size)
  recovery_size_unit=$(echo "${recovery_partition}" | jq -r .size_unit)
  recovery_size_in_bytes=$(convert_unit_to_bytes "$recovery_size_val" "$recovery_size_unit")
  recovery_size_blocks=$(expr "$recovery_size_in_bytes" / "$block_size")

  rootfs_a_offset_val=$(echo "${rootfs_a_partition}" | jq -r .offset)
  if [ -z "$rootfs_a_offset_val" ] || [ "$rootfs_a_offset_val" = "null" ]; then
      rootfs_a_offset_blocks=$(expr "$recovery_offset_blocks" + "$recovery_size_blocks")
  else
      rootfs_a_offset_unit=$(echo "${rootfs_a_partition}" | jq -r .offset_unit)
      rootfs_a_offset_in_bytes=$(convert_unit_to_bytes "$rootfs_a_offset_val" "$rootfs_a_offset_unit")
      rootfs_a_offset_blocks=$(expr "$rootfs_a_offset_in_bytes" / "$block_size")
  fi

  rootfs_a_size_val=$(echo "${rootfs_a_partition}" | jq -r .size)
  rootfs_a_size_unit=$(echo "${rootfs_a_partition}" | jq -r .size_unit)
  rootfs_a_size_in_bytes=$(convert_unit_to_bytes "$rootfs_a_size_val" "$rootfs_a_size_unit")
  rootfs_a_size_blocks=$(expr "$rootfs_a_size_in_bytes" / "$block_size")

  rootfs_b_offset_val=$(echo "${rootfs_b_partition}" | jq -r .offset)
  if [ -z "$rootfs_b_offset_val" ] || [ "$rootfs_b_offset_val" = "null" ]; then
      rootfs_b_offset_blocks=$(expr "$rootfs_a_offset_blocks" + "$rootfs_a_size_blocks")
  else
      rootfs_b_offset_unit=$(echo "${rootfs_b_partition}" | jq -r .offset_unit)
      rootfs_b_offset_in_bytes=$(convert_unit_to_bytes "$rootfs_b_offset_val" "$rootfs_b_offset_unit")
      rootfs_b_offset_blocks=$(expr "$rootfs_b_offset_in_bytes" / "$block_size")
  fi

  rootfs_b_size_val=$(echo "${rootfs_b_partition}" | jq -r .size)
  rootfs_b_size_unit=$(echo "${rootfs_b_partition}" | jq -r .size_unit)
  rootfs_b_size_in_bytes=$(convert_unit_to_bytes "$rootfs_b_size_val" "$rootfs_b_size_unit")
  rootfs_b_size_blocks=$(expr "$rootfs_b_size_in_bytes" / "$block_size")

  var_offset_val=$(echo "${var_partition}" | jq -r .offset)
  if [ -z "$var_offset_val" ] || [ "$var_offset_val" = "null" ]; then
      var_offset_blocks=$(expr "$rootfs_b_offset_blocks" + "$rootfs_b_size_blocks")
  else
      var_offset_unit=$(echo "${var_partition}" | jq -r .offset_unit)
      var_offset_in_bytes=$(convert_unit_to_bytes "$var_offset_val" "$var_offset_unit")
      var_offset_blocks=$(expr "$var_offset_in_bytes" / "$block_size")
  fi

  var_size_val=$(echo "${var_partition}" | jq -r .size)
  var_size_unit=$(echo "${var_partition}" | jq -r .size_unit)
  var_size_in_bytes=$(convert_unit_to_bytes "$var_size_val" "$var_size_unit")
  var_size_blocks=$(expr "$var_size_in_bytes" / "$block_size")

  AVOCADO_OS_VERSION_FINAL="${AVOCADO_OS_VERSION}"
  if [ -z "${AVOCADO_OS_VERSION_FINAL}" ] && [ -f /etc/os-release ]; then
      AVOCADO_OS_VERSION_FINAL=$(grep '^VERSION_ID=' /etc/os-release | cut -d'=' -f2 | tr -d '"')
  fi

  export AVOCADO_SDK_RUNTIME_DIR="${DEPLOY_DIR_IMAGE}"
  export AVOCADO_IMAGE_UBOOT_ENV="${uboot_env_image_file}"
  export AVOCADO_IMAGE_BOOT="${boot_image_file}"
  export AVOCADO_IMAGE_ROOTFS="${rootfs_a_image_file}"
  export AVOCADO_IMAGE_VAR="${var_image_file}"
  export AVOCADO_OS_CODENAME="${AVOCADO_SDK_REPO_RELEASE}"
  export AVOCADO_OS_DESCRIPTION="Avocado ${AVOCADO_SDK_REPO_RELEASE}"
  export AVOCADO_OS_VERSION="${AVOCADO_OS_VERSION_FINAL}"
  export AVOCADO_OS_PLATFORM="${AVOCADO_SDK_TARGET}"
  export AVOCADO_OS_ARCHITECTURE="${architecture}"
  export AVOCADO_OS_AUTHOR="Avocado Linux"
  export AVOCADO_DISK_UUID="${disk_uuid}"
  export AVOCADO_PARTITION_UBOOT_ENV_OFFSET="${uboot_env_offset_blocks}"
  export AVOCADO_PARTITION_UBOOT_ENV_OFFSET_REDUND="${uboot_env_offset_redund_blocks}"
  export AVOCADO_PARTITION_UBOOT_ENV_BLOCKS="${uboot_env_size_blocks}"
  export AVOCADO_PARTITION_BOOTFS_A_OFFSET="${boot_a_offset_blocks}"
  export AVOCADO_PARTITION_BOOTFS_A_BLOCKS="${boot_a_size_blocks}"
  export AVOCADO_PARTITION_BOOTFS_B_OFFSET="${boot_b_offset_blocks}"
  export AVOCADO_PARTITION_BOOTFS_B_BLOCKS="${boot_b_size_blocks}"
  export AVOCADO_PARTITION_RECOVERY_OFFSET="${recovery_offset_blocks}"
  export AVOCADO_PARTITION_RECOVERY_BLOCKS="${recovery_size_blocks}"
  export AVOCADO_PARTITION_ROOTFS_A_OFFSET="${rootfs_a_offset_blocks}"
  export AVOCADO_PARTITION_ROOTFS_A_BLOCKS="${rootfs_a_size_blocks}"
  export AVOCADO_PARTITION_ROOTFS_B_OFFSET="${rootfs_b_offset_blocks}"
  export AVOCADO_PARTITION_ROOTFS_B_BLOCKS="${rootfs_b_size_blocks}"
  export AVOCADO_PARTITION_VAR_OFFSET="${var_offset_blocks}"
  export AVOCADO_PARTITION_VAR_BLOCKS="${var_size_blocks}"

  bbnote "AVOCADO_SDK_RUNTIME_DIR=${AVOCADO_SDK_RUNTIME_DIR}"
  bbnote "AVOCADO_IMAGE_UBOOT_ENV=${AVOCADO_IMAGE_UBOOT_ENV}"
  bbnote "AVOCADO_IMAGE_BOOT=${AVOCADO_IMAGE_BOOT}"
  bbnote "AVOCADO_IMAGE_ROOTFS=${AVOCADO_IMAGE_ROOTFS}"
  bbnote "AVOCADO_IMAGE_VAR=${AVOCADO_IMAGE_VAR}"
  bbnote "AVOCADO_OS_CODENAME=${AVOCADO_OS_CODENAME}"
  bbnote "AVOCADO_OS_DESCRIPTION=${AVOCADO_OS_DESCRIPTION}"
  bbnote "AVOCADO_OS_VERSION=${AVOCADO_OS_VERSION}"
  bbnote "AVOCADO_OS_PLATFORM=${AVOCADO_OS_PLATFORM}"
  bbnote "AVOCADO_OS_ARCHITECTURE=${AVOCADO_OS_ARCHITECTURE}"
  bbnote "AVOCADO_OS_AUTHOR=${AVOCADO_OS_AUTHOR}"
  bbnote "AVOCADO_DISK_UUID=${AVOCADO_DISK_UUID}"
  bbnote "AVOCADO_PARTITION_UBOOT_ENV_OFFSET=${AVOCADO_PARTITION_UBOOT_ENV_OFFSET}"
  bbnote "AVOCADO_PARTITION_UBOOT_ENV_OFFSET_REDUND=${AVOCADO_PARTITION_UBOOT_ENV_OFFSET_REDUND}"
  bbnote "AVOCADO_PARTITION_UBOOT_ENV_BLOCKS=${AVOCADO_PARTITION_UBOOT_ENV_BLOCKS}"
  bbnote "AVOCADO_PARTITION_BOOTFS_A_OFFSET=${AVOCADO_PARTITION_BOOTFS_A_OFFSET}"
  bbnote "AVOCADO_PARTITION_BOOTFS_A_BLOCKS=${AVOCADO_PARTITION_BOOTFS_A_BLOCKS}"
  bbnote "AVOCADO_PARTITION_BOOTFS_B_OFFSET=${AVOCADO_PARTITION_BOOTFS_B_OFFSET}"
  bbnote "AVOCADO_PARTITION_BOOTFS_B_BLOCKS=${AVOCADO_PARTITION_BOOTFS_B_BLOCKS}"
  bbnote "AVOCADO_PARTITION_RECOVERY_OFFSET=${AVOCADO_PARTITION_RECOVERY_OFFSET}"
  bbnote "AVOCADO_PARTITION_RECOVERY_BLOCKS=${AVOCADO_PARTITION_RECOVERY_BLOCKS}"
  bbnote "AVOCADO_PARTITION_ROOTFS_A_OFFSET=${AVOCADO_PARTITION_ROOTFS_A_OFFSET}"
  bbnote "AVOCADO_PARTITION_ROOTFS_A_BLOCKS=${AVOCADO_PARTITION_ROOTFS_A_BLOCKS}"
  bbnote "AVOCADO_PARTITION_ROOTFS_B_OFFSET=${AVOCADO_PARTITION_ROOTFS_B_OFFSET}"
  bbnote "AVOCADO_PARTITION_ROOTFS_B_BLOCKS=${AVOCADO_PARTITION_ROOTFS_B_BLOCKS}"
  bbnote "AVOCADO_PARTITION_VAR_OFFSET=${AVOCADO_PARTITION_VAR_OFFSET}"
  bbnote "AVOCADO_PARTITION_VAR_BLOCKS=${AVOCADO_PARTITION_VAR_BLOCKS}"

  fwup -c -f "${DEPLOY_DIR_IMAGE}/rootdisk.conf" -o "${DEPLOY_DIR_IMAGE}/${MACHINE_SHORT_NAME}-rootdisk.zip"
  fwup -a -d "${DEPLOY_DIR_IMAGE}/${MACHINE_SHORT_NAME}-rootdisk.img" -i "${DEPLOY_DIR_IMAGE}/${MACHINE_SHORT_NAME}-rootdisk.zip" -t complete
}
