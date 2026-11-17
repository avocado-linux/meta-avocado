"""Provision profile name to boot media."""

from . import EngineError, Media

_MEDIA_BY_PROFILE = {
    "tegraflash": Media.NVME,
    "tegraflash-nvme": Media.NVME,
    "tegraflash-mmc": Media.EMMC,
    "tegraflash-emmc": Media.EMMC,
    "tegraflash-sd": Media.SD,
}

ACCEPTED_PROFILES = tuple(_MEDIA_BY_PROFILE)


def media_for_profile(name: str) -> Media:
    """Return the media for an accepted profile; refuse anything else.

    The legacy script warned and fell back to NVMe on an unknown name, which
    would write a board to the wrong medium after a typo.
    """
    try:
        return _MEDIA_BY_PROFILE[name]
    except (KeyError, TypeError):
        raise EngineError(
            f"unknown provision profile {name!r}; accepted profiles: "
            + ", ".join(ACCEPTED_PROFILES)
        ) from None
