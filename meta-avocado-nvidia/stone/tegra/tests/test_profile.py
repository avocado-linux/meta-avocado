"""Profile name to boot media, ported from the oracle's profile case statement."""

import pytest

from avocado_tegraflash import EngineError, Media
from avocado_tegraflash.profile import ACCEPTED_PROFILES, media_for_profile


def test_accepted_profiles_are_the_five_names_in_stable_order():
    assert ACCEPTED_PROFILES == (
        "tegraflash",
        "tegraflash-nvme",
        "tegraflash-mmc",
        "tegraflash-emmc",
        "tegraflash-sd",
    )


@pytest.mark.parametrize(
    "name, media",
    [
        ("tegraflash", Media.NVME),
        ("tegraflash-nvme", Media.NVME),
        ("tegraflash-mmc", Media.EMMC),
        ("tegraflash-emmc", Media.EMMC),
        ("tegraflash-sd", Media.SD),
    ],
)
def test_accepted_profile_maps_to_its_media(name, media):
    assert media_for_profile(name) is media


@pytest.mark.deviation("unknown-profile-refused")
def test_tegraflash_ufs_is_refused_not_defaulted_to_nvme():
    with pytest.raises(EngineError) as exc:
        media_for_profile("tegraflash-ufs")
    assert "tegraflash-ufs" in str(exc.value)


@pytest.mark.deviation("unknown-profile-refused")
def test_refusal_lists_all_five_accepted_names_in_order():
    with pytest.raises(EngineError) as exc:
        media_for_profile("tegraflash-ufs")
    listed = ", ".join(ACCEPTED_PROFILES)
    assert listed in str(exc.value)


@pytest.mark.deviation("unknown-profile-refused")
@pytest.mark.parametrize(
    "name",
    [
        "",
        " ",
        "TegraFlash",
        "TEGRAFLASH-SD",
        "tegraflash ",
        " tegraflash",
        "tegraflash-sd\n",
        "tegraflash-nvme2",
        "my-tegraflash",
        "tegraflash-",
        "tegraflash‑sd",
        "tegraflash-sd\x00",
    ],
)
def test_unknown_name_is_refused(name):
    with pytest.raises(EngineError):
        media_for_profile(name)


@pytest.mark.deviation("unknown-profile-refused")
def test_none_is_refused_with_engine_error():
    with pytest.raises(EngineError):
        media_for_profile(None)  # type: ignore[arg-type]


def test_mutation_default_branch_to_nvme_is_detected(tmp_path, mutant):
    mutated = mutant(
        "profile.py",
        "return _MEDIA_BY_PROFILE[name]",
        "return _MEDIA_BY_PROFILE.get(name, Media.NVME)",
    )
    # The mutant returns NVME for tegraflash-ufs, which the real engine refuses.
    assert mutated.media_for_profile("tegraflash-ufs").value == Media.NVME.value


def test_mutation_sd_mapped_to_emmc_is_detected(tmp_path, mutant):
    mutated = mutant("profile.py", '"tegraflash-sd": Media.SD', '"tegraflash-sd": Media.EMMC')
    # The mutant maps SD to EMMC, contradicting the parametrized mapping test.
    assert mutated.media_for_profile("tegraflash-sd").value == Media.EMMC.value
    assert media_for_profile("tegraflash-sd") is Media.SD
