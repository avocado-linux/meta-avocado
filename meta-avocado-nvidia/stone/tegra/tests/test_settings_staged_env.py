"""What the staged env file says after the boot device was applied, read as bash would."""

import pytest

from avocado_tegraflash import EngineError, Media
from avocado_tegraflash.manifest import Manifest
from avocado_tegraflash.settings import apply_boot_device, verify_staged_env

ENV_NAME = ".env.initrd-flash"
MANIFEST = Manifest(var="images/var.img")
# What apply_boot_device leaves for the nvme profile plus the key it never writes.
NVME_ENV = 'ROOTFS_DEVICE="nvme0n1"\nEXTERNAL_ROOTFS_DRIVE=1\nNO_INTERNAL_STORAGE=1\n'


def work_with(tmp_path, text):
    (tmp_path / ENV_NAME).write_text(text)
    return tmp_path


def test_apply_boot_device_returns_the_device_node_it_wrote(tmp_path):
    env = 'BOOTDEV="x"\nROOTFS_DEVICE="x"\nEXTERNAL_ROOTFS_DRIVE=0\n'
    assert apply_boot_device(work_with(tmp_path, env), Media.NVME, sd_device="") == "nvme0n1"
    (tmp_path / "internal-flash-emmc.xml").write_text("<x/>")
    assert apply_boot_device(tmp_path, Media.EMMC, sd_device="", log=lambda _m: None) == "mmcblk0"
    assert apply_boot_device(tmp_path, Media.SD, sd_device="mmcblk2", log=lambda _m: None) == "mmcblk2"


def test_the_effective_device_is_returned_when_it_matches(tmp_path):
    work = work_with(tmp_path, NVME_ENV)
    assert verify_staged_env(work, MANIFEST, "nvme0n1").device == "nvme0n1"


def test_a_rootfs_device_other_than_the_profiles_is_refused_naming_both(tmp_path):
    work = work_with(tmp_path, NVME_ENV.replace("nvme0n1", "sda"))
    with pytest.raises(EngineError) as exc:
        verify_staged_env(work, MANIFEST, "nvme0n1")
    assert "sda" in str(exc.value) and "nvme0n1" in str(exc.value)


def test_a_missing_rootfs_device_is_refused(tmp_path):
    work = work_with(tmp_path, "BOOTDEV=x\n")
    with pytest.raises(EngineError, match="ROOTFS_DEVICE"):
        verify_staged_env(work, MANIFEST, "nvme0n1")


def test_an_exported_rootfs_device_is_refused_as_non_plain(tmp_path):
    work = work_with(tmp_path, NVME_ENV + 'export ROOTFS_DEVICE="sda"\n')
    with pytest.raises(EngineError, match="sources this file with bash"):
        verify_staged_env(work, MANIFEST, "nvme0n1")


def test_a_datafile_other_than_the_staged_var_image_is_refused(tmp_path):
    work = work_with(tmp_path, NVME_ENV + 'DATAFILE="other.img"\n')
    with pytest.raises(EngineError) as exc:
        verify_staged_env(work, MANIFEST, "nvme0n1")
    assert "DATAFILE" in str(exc.value) and "other.img" in str(exc.value) and "var.img" in str(exc.value)


def test_a_datafile_naming_the_staged_var_image_passes(tmp_path):
    work = work_with(tmp_path, NVME_ENV + 'DATAFILE="var.img"\n')
    verify_staged_env(work, MANIFEST, "nvme0n1")


def test_an_env_file_without_datafile_passes(tmp_path):
    verify_staged_env(work_with(tmp_path, NVME_ENV), MANIFEST, "nvme0n1")


def test_an_empty_datafile_is_refused_because_the_flash_then_deletes_the_data_partition_entry(tmp_path):
    work = work_with(tmp_path, NVME_ENV + 'DATAFILE=""\n')
    with pytest.raises(EngineError, match="DATAFILE"):
        verify_staged_env(work, MANIFEST, "nvme0n1")


# EXTERNAL_ROOTFS_DRIVE is the one other key apply_boot_device writes


@pytest.mark.parametrize("value", ["0", "2"])
def test_an_external_rootfs_drive_other_than_the_one_written_is_refused(tmp_path, value):
    work = work_with(tmp_path, f'ROOTFS_DEVICE="nvme0n1"\nEXTERNAL_ROOTFS_DRIVE={value}\n')
    with pytest.raises(EngineError) as exc:
        verify_staged_env(work, MANIFEST, "nvme0n1")
    assert "EXTERNAL_ROOTFS_DRIVE" in str(exc.value)


def test_a_presigning_vars_override_of_external_rootfs_drive_is_refused(tmp_path):
    work = work_with(tmp_path, NVME_ENV)
    (work / ".presigning-vars").write_text("EXTERNAL_ROOTFS_DRIVE=0\n")
    with pytest.raises(EngineError, match="EXTERNAL_ROOTFS_DRIVE"):
        verify_staged_env(work, MANIFEST, "nvme0n1")


def test_an_external_rootfs_drive_removed_after_the_rewrite_is_refused(tmp_path):
    work = work_with(tmp_path, 'ROOTFS_DEVICE="nvme0n1"\nNO_INTERNAL_STORAGE=1\n')
    with pytest.raises(EngineError, match="EXTERNAL_ROOTFS_DRIVE"):
        verify_staged_env(work, MANIFEST, "nvme0n1")


# the flash emits erase-mmc when EXTERNAL_ROOTFS_DRIVE is 1 and NO_INTERNAL_STORAGE is not 1


def test_the_shipped_no_internal_storage_does_not_erase_emmc(tmp_path):
    assert verify_staged_env(work_with(tmp_path, NVME_ENV), MANIFEST, "nvme0n1").erases_mmc is False


@pytest.mark.parametrize("line", ["", "NO_INTERNAL_STORAGE=0\n"])
def test_an_env_that_is_not_marked_without_internal_storage_erases_emmc(tmp_path, line):
    env = 'ROOTFS_DEVICE="nvme0n1"\nEXTERNAL_ROOTFS_DRIVE=1\n' + line
    assert verify_staged_env(work_with(tmp_path, env), MANIFEST, "nvme0n1").erases_mmc is True


def test_a_presigning_vars_no_internal_storage_decides_the_erase(tmp_path):
    work = work_with(tmp_path, NVME_ENV)
    (work / ".presigning-vars").write_text("NO_INTERNAL_STORAGE=0\n")
    assert verify_staged_env(work, MANIFEST, "nvme0n1").erases_mmc is True
