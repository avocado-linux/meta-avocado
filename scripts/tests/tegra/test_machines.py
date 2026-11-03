import pytest

from avocado_flash_tegra import FlashError
from avocado_flash_tegra.machines import (
    NVIDIA_VENDOR,
    RCM_IDS,
    expected_rcm_id,
    parse_rcm_id,
)


def test_recorded_orin_nano_id():
    assert NVIDIA_VENDOR == "0955"
    assert RCM_IDS == {"avocado-jetson-orin-nano": "0955:7523"}
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


def test_unknown_machine_without_override_names_machine_and_option():
    with pytest.raises(FlashError) as exc:
        expected_rcm_id("avocado-jetson-agx-orin", None)
    assert "avocado-jetson-agx-orin" in str(exc.value)
    assert "--rcm-id" in str(exc.value)


def test_unknown_machine_with_override_uses_override():
    assert expected_rcm_id("avocado-jetson-agx-orin", "0955:7023") == "0955:7023"
