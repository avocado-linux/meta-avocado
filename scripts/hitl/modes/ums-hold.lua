-- HITL mode: ums_hold
--
-- Loaded by imx93-harness.lua via dofile once HARNESS_MODE selects it, so
-- everything the shared runtime defines (cmd, saw, fail, pass, reach_prompt,
-- await_login, login_root, watch, latched_saw, esp_has, settle, and the tail
-- buffer itself) is already in scope here and is deliberately global there.

-- Not an assertion: it parks the board in U-Boot's USB mass-storage mode so the
-- host can write the SD card in place, and holds the console open until killed.
-- The card is exported, not pulled - no reader, no reseating, and no chance of
-- flashing the wrong disk on the bench.
--
-- It prints `version` BEFORE exporting anything, and that ordering is the point.
-- Flashing a bootloader that changes its version AND its config at once, onto a
-- board whose only recovery route (ums) lives inside the bootloader being
-- replaced, is the one move the flashing runbook says to avoid. The banner is
-- the only way to know which of those two this flash is, and it has to be read
-- while backing out is still free.
--
-- `ums` does not return to a prompt - it runs until interrupted - so nothing
-- here waits for one afterwards. A settle just long enough to catch the gadget's
-- own output is all that can be confirmed from this side; whether the host
-- enumerated a disk is a question for the host.
if not reach_prompt(120) then
  fail("did not reach the U-Boot prompt: the board booted through, or the console is unresponsive")
end

cmd("version", 2000)
tio.echo("\r\n---- UBOOT-VERSION-BEGIN ----\r\n" .. tail .. "\r\n---- UBOOT-VERSION-END ----\r\n")

-- mmc 0 is eMMC on this board and mmc 1 is the SD slot; the first argument is
-- the USB controller index, not the disk. Reversing the two exports the eMMC,
-- which on this bench is unprovisioned - so the host would enumerate a disk,
-- the flash would appear to work, and the board would still boot the old card.
tio.write("ums 0 mmc 1\r\n")
settle(5000)
tio.echo("\r\n---- UMS-STARTED ----\r\n" .. tail .. "\r\n---- UMS-READY ----\r\n")

-- Hold the console so the export stays up while the host writes. Killing this
-- process is what ends it; the caller does that once fwup is done.
local held_ms = 0
while held_ms < 2400000 do
  settle(5000)
  held_ms = held_ms + 5000
end
-- End the export on the BOARD before letting go of the console. Dropping the
-- host end does not stop `ums` - U-Boot keeps exporting to nobody, and the
-- next power cycle happens with the gadget still live, which is how the USB
-- controller ends up refusing to initialise afterwards.
tio.write("\003")
settle(2000)
tio.echo("\r\nUMS hold expired after 40 minutes; export stopped.\r\n")
os.exit(0)
