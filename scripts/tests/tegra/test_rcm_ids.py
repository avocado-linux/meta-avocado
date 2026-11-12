import pytest

from avocado_flash_tegra import FlashError
from avocado_flash_tegra.rcm import NVIDIA_VENDOR, expected_rcm_id, parse_rcm_id


def test_recorded_orin_nano_id():
    assert NVIDIA_VENDOR == "0955"
    assert expected_rcm_id("avocado-jetson-orin-nano", None) == "0955:7523"


def test_mixed_case_override_returned_lowercase():
    assert parse_rcm_id("0955:7A23") == "0955:7a23"
    assert expected_rcm_id("avocado-jetson-orin-nano", "0955:7A23") == "0955:7a23"


@pytest.mark.parametrize("bad", ["0955-7523", "7523", "0955:zzzz", "", "0955:75233"])
def test_malformed_override_refused(bad):
    with pytest.raises(FlashError):
        parse_rcm_id(bad)


def test_non_nvidia_vendor_refused():
    with pytest.raises(FlashError) as exc:
        parse_rcm_id("1fc9:0146")
    assert "0955" in str(exc.value)


def test_non_nvidia_override_refused_through_expected():
    with pytest.raises(FlashError):
        expected_rcm_id("avocado-jetson-orin-nano", "1fc9:0146")


def test_machine_without_entry_and_without_override_names_machine_and_both_options():
    with pytest.raises(FlashError) as exc:
        expected_rcm_id("avocado-jetson-nonexistent", None)
    msg = str(exc.value)
    assert "avocado-jetson-nonexistent" in msg
    assert "--rcm-id" in msg
    assert "avocado-flash boards" in msg


def test_machine_without_recorded_id_refuses_naming_both_options():
    with pytest.raises(FlashError) as exc:
        expected_rcm_id("avocado-jetson-orin-nx", None)
    msg = str(exc.value)
    assert "avocado-jetson-orin-nx" in msg
    assert "--rcm-id" in msg
    assert "avocado-flash boards" in msg


def test_unknown_machine_with_override_uses_override():
    assert expected_rcm_id("avocado-jetson-nonexistent", "0955:7023") == "0955:7023"
