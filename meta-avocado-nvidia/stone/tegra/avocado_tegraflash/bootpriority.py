"""Make the target medium the firmware's first boot choice.

The flash resets the UEFI variable store, and on an empty store the firmware
sorts BootOrder once by DefaultBootPriority from L4TConfiguration.dtbo. The stock
list puts usb and nvme ahead of sd, so the target class is moved to the front.
"""

from collections.abc import Callable, Mapping
from pathlib import Path

from . import EngineError, Media
from .files import copy_replacing_link
from .runner import Runner

NODE = (
    "/fragment@0/__overlay__/firmware/uefi/variables/"
    "gNVIDIATokenSpaceGuid/DefaultBootPriority"
)

# fdtget reads a local file; a run past this is a hung tool, not a slow read.
FDTGET_TIMEOUT = 5


def _read(runner: Runner, dtbo: Path, env: Mapping[str, str]) -> tuple[int, str]:
    # Oracle line 606 leaves fdtget's stderr on the terminal.
    status, out = runner.capture(
        ["fdtget", "-t", "s", str(dtbo), NODE, "data"],
        env=env,
        discard_stderr=False,
        timeout=FDTGET_TIMEOUT,
    )
    return status, out.rstrip("\n")


def set_first(
    runner: Runner,
    work_dir: Path,
    media: Media,
    *,
    env: Mapping[str, str],
    log: Callable[[str], None] = print,
) -> tuple[str, str]:
    dtbo = Path(work_dir) / "L4TConfiguration.dtbo"
    status, stock = _read(runner, dtbo, env)
    if status != 0:
        raise EngineError(f"cannot read DefaultBootPriority from {dtbo}")
    classes = stock.split(",") if stock else []
    # Oracle line 611, `IFS=, read -ra`: one trailing delimiter ends the last field.
    if classes and classes[-1] == "":
        classes.pop()
    new = ",".join([media.value] + [c for c in classes if c != media.value])
    # Edit a private copy: a link would carry the change back into the staged BSP.
    if dtbo.is_symlink():
        copy_replacing_link(dtbo.resolve(), dtbo)
    if runner.run(["fdtput", "-t", "s", str(dtbo), NODE, "data", new], env=env) != 0:
        raise EngineError(f"cannot set DefaultBootPriority in {dtbo}")
    _, got = _read(runner, dtbo, env)
    if got != new:
        raise EngineError(f"DefaultBootPriority did not take in {dtbo}")
    log(f"UEFI DefaultBootPriority: {new} (was {stock})")
    return new, stock
