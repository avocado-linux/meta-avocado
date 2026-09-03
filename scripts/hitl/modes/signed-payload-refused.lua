-- HITL mode: signed_payload_refused
--
-- Loaded by imx93-harness.lua via dofile once HARNESS_MODE selects it, so
-- everything the shared runtime defines (cmd, saw, fail, pass, reach_prompt,
-- await_login, login_root, watch, latched_saw, esp_has, settle, and the tail
-- buffer itself) is already in scope here and is deliberately global there.

-- Offer the firmware a payload the enrolled key database does not vouch for and
-- assert it is REFUSED.
--
-- THE ASSERTION IS INVERTED FROM EVERY OTHER MODE IN THIS FILE. The others pass
-- when the board reaches a login prompt; this one passes when it does NOT.
-- Reaching a login prompt here is the failure, because it means the firmware
-- started an unverifiable payload while reporting that Secure Boot was
-- enforcing.
--
-- It is the only evidence that enforcement is PERFORMED rather than merely
-- reported, which is why nothing below reads the `SecureBoot` variable.
-- `SecureBoot=1` is the firmware's own claim about itself, and a board that
-- boots a correctly signed payload proves only that the good path works -
-- neither observes a refusal. This mode exists to replace both inferences with
-- an observation.
--
-- THE FIXTURE COMES FROM THE BUILD. The boot partition carries
-- `Image.unsigned`, a copy of the unsigned kernel `Image` that avocado-stone's
-- do_deploy takes from the same bytes it hands sbsign, staged there by the
-- boot-integrity-poc manifest entry. Nothing boots it.
--
-- It used to be a manual step - copy the Image onto the card with `--ums-hold`
-- before running this mode - and that is why it is worth stating that it no
-- longer is. A test whose fixture a human assembles is a test that quietly
-- stops running: this mode failed with "stage the unsigned kernel Image there
-- first", and the cheapest way past that message is to skip the assertion
-- rather than to satisfy it. The build now cannot produce a PoC image whose
-- enforcement claim has no way to be falsified.
--
-- The distinct filename is deliberate - loading a bare `Image` would silently
-- pick up whatever a future manifest happens to stage under that name, and this
-- check must never be satisfied by a file nobody chose.
--
-- The load address, device tree and boot command are the board's own
-- (`image_addr`, `load_devicetree`, `avocado_boot`), so a refusal observed here
-- is a refusal on the real boot path rather than on a hand-built one.
if not reach_prompt(180) then fail("never reached the U-Boot prompt") end

-- Liveness off output the BOARD produces, never off a string this script
-- sent - a console echoes its own input, and matching that reports success
-- against a board that ran nothing.
cmd("version", 1500)
if not saw("U%-Boot") then fail("no version banner - console not actually live") end

-- Refuse to run against firmware whose boot command is not the EFI hand-off.
-- On a token-absent build `avocado_boot` is `bootm` on a FIT: it would fail on
-- a bare Image, and that failure would have nothing to do with signature
-- checking. "bootefi" appears in the ANSWER, not in the question sent, so the
-- echo cannot satisfy it.
cmd("printenv avocado_boot", 1500)
if not saw("bootefi") then
  fail("avocado_boot does not run bootefi - this is not a boot-integrity-poc " ..
       "build, and any refusal seen here would be unrelated to signing")
end

-- Slot selection, bootargs and the device tree are the real ones. A missing
-- device tree is one of the unrelated failures this mode must never report as
-- a refusal, so it is loaded first and its success asserted. `load` prints
-- "bytes read" only on a successful read, and that phrase is absent from the
-- command sent.
cmd("run avocado_boot_init", 1500)
cmd("run load_devicetree", 4000)
if not saw("bytes read") then
  fail("the device tree did not load - fix that first; a boot failure now " ..
       "would say nothing about signature enforcement")
end

-- The fixture lives on the ESP, not on ${bootpart}. boot is 128 MiB and is
-- already ~126 MiB full of fitImage, BOOTAA64.EFI and the dtb, so a 34 MiB
-- unsigned kernel does not fit there; the ESP ships empty apart from the
-- runtime-written ubootefi.var. See avocado-stone.bbappend for the arithmetic.
--
-- Resolved by NAME, for the reason part two of keydb_immutable spells out at
-- length: this card went from 8 partitions to 10 inside two days, so a
-- hardcoded index would pass today by pointing at the right partition and
-- later pass by pointing at the wrong one.
cmd("part number ${devtype} ${devnum} esp espp; echo 'ESPPART''='${espp}", 4000)
local esppart = string.match(tail, "ESPPART=(%S+)")
if not esppart or esppart == "" then
  fail("could not resolve a partition named 'esp' on the boot medium - the " ..
       "unsigned fixture cannot be located, so nothing can be offered to the " ..
       "firmware and nothing would be refused")
end

-- Overwrite image_addr with the UNSIGNED payload, replacing the signed one the
-- board would otherwise run. Asserting this read is what separates "the
-- firmware refused it" from "there was nothing to refuse".
cmd("load ${devtype} ${devnum}:${espp} ${image_addr} Image.unsigned", 15000)
if not saw("bytes read") then
  fail("Image.unsigned did not load from the ESP (partition " .. esppart ..
       "). The build stages it there under boot-integrity-poc, so this means " ..
       "the card predates that change or was flashed from a token-absent " ..
       "build - reflash. Nothing was offered to the firmware, so nothing " ..
       "was refused")
end
tio.echo("\r\n>>> unsigned payload loaded at image_addr <<<\r\n")

-- Latch on a CLEARED tail, immediately before the command that decides the
-- verdict. Both markers survive tail eviction once latched, and neither can be
-- satisfied by text printed earlier in this run or left over from before the
-- power cycle. Neither appears in the command sent, so neither can be
-- satisfied by the console echoing it back.
tail = ""
watch("Image not authenticated")
watch("login:")

tio.write("run avocado_boot\r\n")
tio.msleep(300)

-- Wait for a VERDICT rather than for a fixed duration. A refusal lands within
-- seconds of the hand-off, a boot to a login prompt takes far longer, and a
-- window generous enough for the second would be spent in full on every run of
-- the first - which the front end's 300s cap on the whole run cannot afford.
-- Breaking on either marker keeps both cases inside it.
local verdict_deadline = os.time() + 120
while os.time() < verdict_deadline do
  settle(1000)
  if latched_saw("login:") then break end
  if latched_saw("Image not authenticated") then
    -- A refusal returns control to U-Boot, so nothing should follow. Watch a
    -- little longer anyway before calling it one: the claim being made is
    -- that the payload never ran, and that is a claim about what happens
    -- AFTER the message as much as about the message itself.
    settle(20000)
    break
  end
end

-- The outcome this whole change exists to prevent: the firmware reports
-- enforcement and starts whatever it is handed.
if latched_saw("login:") then
  fail("the board BOOTED the unsigned payload to a login prompt - Secure " ..
       "Boot is reported and NOT performed, which is worse than the honest " ..
       "SecureBoot=0 this started from. Do not ship the enrolment.")
end

-- Not booting is not enough on its own. A bad load address, a missing device
-- tree or a truncated payload all leave a board that does not boot, and
-- recording any of them as a refusal would vouch for enforcement that was
-- never exercised. U-Boot prints "Image not authenticated" from
-- efi_load_pe() only when efi_image_authenticate() rejected the payload, so
-- that string - and nothing weaker - is the evidence.
if not latched_saw("Image not authenticated") then
  fail("the board did not boot, but U-Boot never reported an image " ..
       "authentication failure - indistinguishable from an unrelated boot " ..
       "failure, and NOT evidence that enforcement was exercised")
end

pass("bootefi refused a payload not signed against the enrolled db and the " ..
     "board never reached a login prompt - enforcement is performed, not " ..
     "merely reported")
