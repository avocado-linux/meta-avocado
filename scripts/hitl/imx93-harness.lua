-- tio script driving the avocado-imx93-frdm console for HITL assertions.
-- Invoked by imx93-harness.sh, which schedules the power cycle and passes the
-- mode in HARNESS_MODE / HARNESS_ARG.
--
-- PACING IS THE WHOLE GAME HERE, and it is the one thing that has repeatedly
-- gone wrong on this board. tio.read(n, t) returns the MOMENT bytes are waiting
-- rather than sleeping out its timeout. A loop paced on that read spins during a
-- boot flood and pushes thousands of bytes per second at a console whose
-- autoboot poll drains roughly 100 chars/sec, overrunning the LPUART FIFO. That
-- produced three separate and entirely wrong "the board is broken" conclusions.
-- Every wait below is tio.msleep. Never pace on a read timeout.

local MODE = os.getenv("HARNESS_MODE") or ""
local ARG = os.getenv("HARNESS_ARG") or ""
local TAIL_MAX = 24000

local tail = ""

-- Markers are LATCHED as they stream past, not looked for in the tail at the
-- end. A full boot is roughly 100 KB and the tail is bounded, so an early marker
-- like "Booting B" is evicted long before "login:" arrives - asking for both to
-- coexist in the buffer is a test that can never pass on a long boot. This is a
-- real defect that was written, run, and observed failing here before being
-- fixed; keep the latch.
local latched = {}
local watched = {}

local function watch(p) watched[p] = true; latched[p] = latched[p] or false end
local function latched_saw(p) return latched[p] == true end

local function absorb(c)
  tail = tail .. c
  for p, _ in pairs(watched) do
    if not latched[p] and string.match(tail, p) then latched[p] = true end
  end
  if #tail > TAIL_MAX then tail = string.sub(tail, -TAIL_MAX) end
end

local function saw(p) return string.match(tail, p) ~= nil end

-- Sleep `ms` of REAL time, draining whatever arrives. The short read timeout is
-- only so a quiet line does not stall; the msleep is what costs the time.
local function settle(ms)
  local left = ms
  while left > 0 do
    tio.msleep(100)
    left = left - 100
    local c = tio.read(4096, 20)
    if c then absorb(c) end
  end
end

local function fail(msg)
  tio.echo("\r\nRESULT: FAIL - " .. msg .. "\r\n")
  tio.echo("---- tail ----\r\n" .. tail .. "\r\n--------------\r\n")
  os.exit(1)
end

local function pass(msg)
  tio.echo("\r\nRESULT: PASS - " .. msg .. "\r\n")
  os.exit(0)
end

-- Interrupt autoboot and land on the U-Boot prompt. Autoboot is unkeyed, so a
-- newline suffices; newlines specifically because leftover bytes become
-- commands at the prompt and an empty command is harmless.
-- Ctrl-C leads the newline, and it is what makes a wedged board recoverable.
-- Autoboot is unkeyed so 0x03 interrupts it exactly as a newline does; at a
-- prompt or a getty it does nothing. But if the board is still running `ums`
-- from a previous session - which survives the host end being killed - Ctrl-C is
-- the ONLY thing that ends it. Without this a stale export leaves the console
-- emitting a progress spinner that matches no prompt, so every later assertion
-- reports an unresponsive console and the cause is invisible.
local function reach_prompt(deadline_s)
  local deadline = os.time() + deadline_s
  local window_seen = false
  tail = ""
  while os.time() < deadline do
    tio.write("\003")
    tio.msleep(50)
    tio.write("\r\n")
    tio.msleep(200)
    local c = tio.read(4096, 20)
    if c then absorb(c) end
    if saw("u%-boot=>") then return true end
    -- Clearing the tail on the window is the point, not tidiness. Before the
    -- reset the board sits at a getty echoing these newlines, so the buffer
    -- fills with "login:". Without the wipe the boot-through test below matches
    -- that STALE text the instant U-Boot prints its prompt and bails in the same
    -- millisecond the window opens, having never waited for it.
    if not window_seen and saw("Hit any key") then
      window_seen = true
      tail = ""
    end
    if window_seen and saw("login:") then
      return false
    end
  end
  return false
end

local function cmd(line, settle_ms)
  tail = ""
  tio.write(line .. "\r\n")
  tio.msleep(300)
  settle(settle_ms or 1200)
end

-- Wait for the board to boot through to userspace without sending anything.
-- Passive by construction: a send here would interrupt the autoboot it is
-- waiting on.
local function await_login(deadline_s)
  local deadline = os.time() + deadline_s
  tail = ""
  while os.time() < deadline do
    tio.msleep(300)
    local c = tio.read(4096, 50)
    if c then absorb(c) end
    if saw("login:") then return true end
  end
  return false
end

-- Log in as root, or fail naming WHICH way it went wrong.
--
-- Shared by every mode that needs a shell. It used to be two copies - one
-- inline, one a local inside keydb_immutable - which is why the two reported
-- the same failure with different wording.
--
-- The password branch is the point. An image built WITHOUT
-- kas/target/bringup.yml has a locked root: avocado-users ships `root:*:`, and
-- the empty-root-password image feature only preserves an already-empty
-- password rather than creating one, so only that overlay's
-- AVOCADO_DEV_ROOT_LOGIN=1 unlocks it. The board then boots perfectly, reaches
-- a login prompt, and answers `root` with `Password:` - and the old message,
-- "did not reach a root shell", reads as a wedged or broken board. It cost a
-- full build-flash-assert cycle to work out that the image was simply built
-- without the overlay, so the message now says so.
local function login_root()
  cmd("root", 4000)
  if saw("avocado%-imx93%-frdm:~#") then return end

  -- Checked before the generic failure because it is the specific, actionable
  -- cause. "Password:" comes from the getty, not from the string sent, so the
  -- console echoing its own input cannot satisfy it.
  if saw("Password:") then
    fail("the console prompted root for a PASSWORD, so this image has no " ..
         "passwordless login and no assertion needing a shell can run. This " ..
         "is a BUILD problem, not a board problem: avocado-users ships a " ..
         "locked root (root:*:) and only AVOCADO_DEV_ROOT_LOGIN=1 unlocks it, " ..
         "which kas/target/bringup.yml sets. Rebuild with that overlay in the " ..
         "kas chain and reflash")
  end

  fail("did not reach a root shell and the console did not ask for a " ..
       "password either - the board is not where this mode expects it")
end

if MODE == "env_lockdown" then
  if not reach_prompt(180) then fail("never reached the U-Boot prompt") end
  tio.echo("\r\n>>> at the prompt <<<\r\n")

  -- Prove the console is live before trusting anything it prints. Match on
  -- output the board produces, never on a string this script transmitted - a
  -- getty echoes its own input, and matching that reports success against a
  -- board that ran nothing.
  cmd("version", 1500)
  if not saw("U%-Boot") then fail("no version banner - console not actually live") end

  -- (a) a saved bootcmd must NOT take effect: it is absent from the permit list,
  -- so env_flags_validate rejects it on import and the compiled-in default runs.
  cmd("env set bootcmd 'echo HARNESS_HIJACK_MARKER'", 800)
  cmd("saveenv", 4000)
  cmd("reset", 500)

  if not reach_prompt(180) then fail("board did not come back after reset") end
  cmd("printenv bootcmd", 1500)
  if saw("HARNESS_HIJACK_MARKER") then
    fail("saved bootcmd SURVIVED - the offline env bypass is OPEN")
  end
  tio.echo("\r\n>>> (a) saved bootcmd rejected <<<\r\n")

  -- (b) a saved avocado_boot_slot MUST still take effect, or the permit list
  -- fixed the hole by breaking OTA, which is worse than the hole.
  cmd("env set avocado_boot_slot b", 800)
  cmd("saveenv", 4000)
  watch("Booting B")
  cmd("reset", 500)

  if not await_login(240) then
    fail("board did not reach a login prompt after the slot switch")
  end
  if not latched_saw("Booting B") then
    fail("avocado_boot_slot=b did not take effect - OTA slot switching is broken")
  end
  pass("saved bootcmd rejected, saved avocado_boot_slot honoured, board booted")
end

if MODE == "slot_boots" then
  if ARG ~= "a" and ARG ~= "b" then fail("slot_boots needs HARNESS_ARG a or b") end
  if not reach_prompt(180) then fail("never reached the U-Boot prompt") end
  cmd("env set avocado_boot_slot " .. ARG, 800)
  cmd("saveenv", 4000)
  local want = (ARG == "a") and "Booting A" or "Booting B"
  watch(want)
  cmd("reset", 500)
  if not await_login(240) then fail("slot " .. ARG .. " did not reach a login prompt") end
  if not latched_saw(want) then fail("expected '" .. want .. "' and did not see it") end
  pass("slot " .. ARG .. " booted to a login prompt")
end

if MODE == "uefi_var_persists" then
  if not reach_prompt(180) then fail("never reached the U-Boot prompt") end

  -- Prove the console is live off output the BOARD produces, never off a
  -- string this script sent - a getty echoes its own input, and matching that
  -- reports success against a board that ran nothing.
  cmd("version", 1500)
  if not saw("U%-Boot") then fail("no version banner - console not actually live") end

  -- `setenv -e` needs a variable store to write to. On firmware built with
  -- CONFIG_EFI_MM_COMM_TEE and no StandAloneMM behind it there is none, so this
  -- fails - which is the correct outcome on a board that has not been flashed
  -- with the PoC bootloader, and is why the failure message says so rather
  -- than reporting a generic write error.
  --
  -- -nv is what makes the variable non-volatile and therefore a persistence
  -- test at all; without it the value lives in memory and the check below
  -- would be measuring nothing. -bs is required alongside it.
  cmd("setenv -e -nv -bs AvocadoHitlProbe HITLPROBEVALUE", 2000)
  if saw("Cannot set") or saw("Failed") or saw("not supported") then
    fail("setenv -e was refused - no UEFI variable store on this firmware. " ..
         "Expected until the PoC bootloader (CONFIG_EFI_VARIABLE_FILE_STORE) is flashed.")
  end

  cmd("printenv -e AvocadoHitlProbe", 2000)
  if not saw("HITLPROBEVALUE") then
    fail("the variable did not read back in the SAME session, so the write " ..
         "never landed - this is a store problem, not a persistence problem")
  end
  tio.echo("\r\n>>> variable written and read back in-session <<<\r\n")

  -- Latch the marker BEFORE the reset. A boot is far larger than the tail
  -- buffer, so a value matched only afterwards would already have been evicted.
  watch("HITLPROBEVALUE")

  -- A warm reset rather than a power cycle, deliberately. The PoC store is a
  -- file on the EFI system partition, so it is on the medium either way and the
  -- two are equivalent for this property. The .sh already power-cycles once at
  -- the start, so the board has been cold-started within this run.
  cmd("reset", 500)
  if not reach_prompt(180) then fail("board did not come back after reset") end

  tail = ""
  cmd("printenv -e AvocadoHitlProbe", 2500)
  if not saw("HITLPROBEVALUE") then
    fail("the variable did not survive the reset - even the PoC store is not persisting")
  end

  pass("UEFI variable written, survived a reset, and read back. " ..
       "NOTE: this proves PERSISTENCE only. The PoC store is a file on a FAT " ..
       "partition and is not tamper-resistant.")
end

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
if MODE == "ums_hold" then
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
end

-- Stop an export this script is not holding: the caller's cleanup path, and the
-- way to recover a board left exporting by a previous run. Idempotent - Ctrl-C
-- at an idle prompt does nothing, so running it on a board that is not
-- exporting is safe and still confirms the prompt is reachable.
if MODE == "ums_stop" then
  if not reach_prompt(60) then
    fail("could not reach the U-Boot prompt to stop an export")
  end
  pass("export stopped; board is at the U-Boot prompt")
end

-- Boot, then read the record the on-device reporter publishes and check it
-- carries BOTH halves. Enforcement alone is the failure this whole change
-- exists to prevent, so a record with one and not the other fails here rather
-- than reaching a fleet view.
if MODE == "boot_integrity_report" then
  if not reach_prompt(180) then fail("never reached the U-Boot prompt") end
  cmd("reset", 500)
  if not await_login(240) then fail("board did not reach a login prompt") end

  -- Passwordless root, which only the bringup overlay provides; login_root
  -- names that as the cause when it is missing.
  login_root()

  -- Match ONLY on strings the file contains. The getty echoes its own input, so
  -- a pattern that also appears in the command sent would report success against
  -- a board that ran nothing - the failure this harness's header warns about.
  -- `cat /run/avocado-boot-integrity` carries neither key below.
  cmd("cat /run/avocado-boot-integrity", 4000)

  if not saw("enforcement=") then
    fail("no enforcement value in the record - the reporter did not run")
  end
  if not saw("rot_state=") then
    fail("record carries enforcement with no root-of-trust indicator")
  end
  -- Same echo rule as above, and it is the test to apply to any field added
  -- here later: `keydb_origin=` occurs in the record but nowhere in the text of
  -- the command sent, so matching it cannot be satisfied by the getty's echo.
  if not saw("keydb_origin=") then
    fail("record carries no keydb_origin field - the reporter predates the key-database contract")
  end

  -- EXACT values from here down, not merely "not the worst value". Requiring
  -- field presence and rejecting two known-bad readings let the original broken
  -- state pass this mode: `enforcement=disabled` with `keydb_origin=unknown`
  -- satisfied every check above, which is precisely SecureBoot off and no
  -- enrolled database - the state this change exists to replace. This mode is
  -- the positive validation of that premise, so it has to assert the premise.
  --
  -- Safe against the getty echo for the same reason the presence checks are:
  -- the command sent is `cat /run/avocado-boot-integrity`, which contains none
  -- of these value strings, so a match can only come from the record.
  if not saw("enforcement=enabled") then
    fail("enforcement does not read `enabled` - the firmware is not gating anything, " ..
         "so no other field in this record is worth reading. efivarfs absent reads " ..
         "`unavailable`; secure boot off reads `disabled`; both fail here")
  end

  -- The expected result on THIS board, and the direction that matters. Its
  -- SRK_HASH fuse is burned byte-swapped, so AHAB cannot be closed and nothing
  -- anchors the firmware. An indicator reading authenticated is a defect in the
  -- reader, not good news, and must fail rather than be reported as a pass.
  if not saw("rot_state=unauthenticated") then
    fail("root of trust does not read `unauthenticated` on a board whose AHAB " ..
         "lifecycle is open and cannot be closed. `authenticated` is a reader " ..
         "defect rather than good news; `unavailable` means enforcement was not " ..
         "readable either")
  end

  -- The PoC store is a file on a FAT partition, so this is the only honest
  -- value here. Asserted rather than assumed because a reader that started
  -- claiming otherwise would be the same class of defect as an authenticated
  -- root of trust.
  if not saw("store_trust=unauthenticated") then
    fail("store_trust does not read `unauthenticated` - the PoC keeps variables " ..
         "in a file anyone able to write the boot medium can edit, and any other " ..
         "value overstates it")
  end

  -- The claim the whole enrolment exists to earn. The reporter honours it only
  -- when the enrolled db matches the certificate the image shipped, so
  -- `unknown` here means either the preseed did not happen or the enrolled key
  -- database is not ours - and both must fail rather than pass quietly.
  -- `%-` because saw() takes a Lua PATTERN, where a bare `-` is the lazy
  -- repetition quantifier rather than a hyphen. Unescaped, this never matches
  -- and the mode fails on a record that plainly carries the value - observed on
  -- hardware, where the other three assertions passed and this one did not.
  -- The three values above contain no magic characters, which is why they are
  -- written plainly and this one cannot be.
  if not saw("keydb_origin=firmware%-resident") then
    fail("keydb_origin does not read `firmware-resident` - the key database was " ..
         "either not compiled into the bootloader, or does not match the " ..
         "certificate this image shipped. The reporter downgrades to `unknown` " ..
         "in both cases and this mode must not pass on either")
  end

  pass("record reads enforcement=enabled, rot_state=unauthenticated, " ..
       "store_trust=unauthenticated and keydb_origin=firmware-resident - " ..
       "enforcement is on, its root of trust is honestly unanchored, and the " ..
       "key database is corroborated as firmware-resident")
end

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
if MODE == "signed_payload_refused" then
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
end

-- Assert the enrolled key database cannot be replaced, covering BOTH halves of
-- the spec requirement in one run:
--
--   part one,   RUNTIME  - a write to PK from a booted root shell is refused and
--                          leaves PK byte-identical;
--   part two-a, OVERRIDE - a well-formed rival store naming a DIFFERENT PK is
--                          written over ubootefi.var on the ESP, and the
--                          enrolled PK still does not change;
--   part two-b, ABSENCE  - deleting the variable store outright leaves the SAME
--                          PK in place.
--
-- Two-a and two-b are different claims and the weaker one is easy to mistake for
-- the stronger. Absence shows only that the seed is used when nothing competes -
-- firmware with no precedence rule at all passes it. Override is what shows the
-- seed WINS. Part two used to be the absence leg alone, and its verdict read as
-- though it had established precedence.
--
-- The hash is read ONCE, before any tamper, and compared twice. Re-reading it
-- after a tamper and comparing that against itself would pass on a PK that had
-- been substituted wholesale, since a substituted variable hashes consistently
-- with itself.
--
-- Neither half may be skipped. A half that cannot run fails the mode; recording
-- a PASS for a check that was never exercised is the outcome this mode exists
-- to prevent.
if MODE == "keydb_immutable" then
  local PK = "/sys/firmware/efi/efivars/PK-8be4df61-93ca-11d2-aa0d-00e098032b8c"

  -- Every marker below is built by concatenating two adjacent shell string
  -- literals, so the bytes SENT carry `PKPROBE''-` while the bytes the board
  -- PRINTS carry `PKPROBE-`. The getty echoes its own input, and this is what
  -- keeps that echo from satisfying the pattern. `cmd` clears the tail before
  -- writing, so nothing matched here can be text left over from earlier.
  local function probe_pk()
    cmd("s=$(wc -c < " .. PK .. "); h=$(sha256sum < " .. PK ..
        " | cut -c1-64); printf 'PKPROBE''-%s-%s\\n' \"$s\" \"$h\"", 4000)
    -- The optional whitespace is not cosmetic: some `wc` implementations pad the
    -- count into a fixed-width field, and command substitution keeps the leading
    -- spaces. Without it the probe would read as "PK absent" on such an image.
    return string.match(tail, "PKPROBE%-%s*(%d+)%-(%x+)")
  end

  if not reach_prompt(180) then fail("never reached the U-Boot prompt") end
  cmd("reset", 500)
  if not await_login(240) then fail("board did not reach a login prompt") end
  login_root()

  ---------------------------------------------------------------- part one ---

  -- A read-only efivarfs would refuse the write for a reason that has nothing
  -- to do with the key database, and that refusal would read exactly like the
  -- one being tested for. So the mount state is established before any
  -- conclusion is drawn from a failed write. awk concatenates the two literals,
  -- so the printed key differs from the sent one.
  cmd("awk '$3==\"efivarfs\"{print \"EFIVARFSOPTS\" \"=\" $4}' /proc/mounts", 3000)
  local opts = string.match(tail, "EFIVARFSOPTS=(%S+)")
  if not opts then
    fail("efivarfs is not mounted - there is no runtime variable interface to " ..
         "write to, and PK cannot be read either, so neither half can run")
  end

  -- Read PK BEFORE branching on writability. Reading works on a read-only
  -- mount, and part two compares against this baseline whichever way part one
  -- goes - so taking it here is what lets the offline half run on a platform
  -- that has no runtime write interface at all.
  local size0, hash0 = probe_pk()
  if not size0 then
    fail("PK did not read back from efivarfs - either the key database is not " ..
         "enrolled, or the image carries no wc/sha256sum for the probe to use. " ..
         "Either way there is nothing whose immutability could be tested")
  end
  if size0 == "0" then fail("PK is present but empty - nothing to protect") end
  tio.echo("\r\n>>> PK recorded before any tamper: " .. size0 .. " bytes, " ..
           hash0 .. " <<<\r\n")

  -- Does a runtime write interface exist at all? Three outcomes, and collapsing
  -- any two of them is what this branch exists to prevent:
  --
  --   rw            - the interface exists, so the write test below is the real
  --                   evidence and it runs unchanged.
  --   ro, no SetVariableRT
  --                 - U-Boot exposes no runtime SetVariable, so the kernel
  --                   mounts efivarfs ro and REFUSES to remount it rw. The
  --                   runtime route is absent, which closes it as surely as a
  --                   refused write. Reported as absence, never as a refusal:
  --                   "no interface" and "the store said no" are different
  --                   claims and only the second is evidence about the key
  --                   database.
  --   ro, other     - inconclusive, and it stays a failure. A mount that could
  --                   have been made writable and was not tells us nothing.
  --
  -- The remount is ATTEMPTED rather than assumed either way. That is what keeps
  -- this honest across a firmware bump: a future U-Boot that gains
  -- SetVariableRT comes back rw here and silently upgrades to the strict write
  -- test, instead of coasting on an absence verdict that stopped being true.
  local runtime_writable = string.match(opts, "^rw") ~= nil
  local runtime_absent = false

  if not runtime_writable then
    -- The kernel's reason lands in dmesg, and it is counted HERE rather than
    -- matched later for two reasons that each produced a wrong verdict on the
    -- first attempt:
    --
    --   `cmd` clears the tail before every write, so a match attempted after
    --   the next command inspects that command's output instead of this one's.
    --   The count is therefore folded into this same tail.
    --
    --   The search string cannot be spelled literally in what is SENT. The
    --   getty echoes its own input, so a bare grep for the kernel's wording
    --   would put that wording on the console and the match would be satisfied
    --   by the echo rather than by dmesg. Both the pattern and the marker are
    --   split across two adjacent shell literals, which the shell joins and the
    --   echo does not - the same guard every other probe in this mode uses.
    cmd("mount -o remount,rw /sys/firmware/efi/efivars > /tmp/hitl.rm 2>&1; " ..
        "echo 'REMOUNTRC''='$?; cat /tmp/hitl.rm; " ..
        "n=$(dmesg | grep -c 'SetVariable''RT'); printf 'NOSETVAR''RT=%s\\n' \"$n\"",
        5000)
    if not string.match(tail, "REMOUNTRC=(%d+)") then
      fail("the remount attempt produced no return code - the shell is not " ..
           "running what it is sent, so no verdict here can be trusted")
    end
    local novar = string.match(tail, "NOSETVARRT=(%d+)")
    if not novar then
      fail("the dmesg probe produced no count - the shell is not running what " ..
           "it is sent, so no verdict here can be trusted")
    end

    -- Re-read the mount table rather than trusting the return code: what
    -- matters is the state that resulted, not what the command claimed.
    cmd("awk '$3==\"efivarfs\"{print \"EFIVARFSNOW\" \"=\" $4}' /proc/mounts", 3000)
    local opts2 = string.match(tail, "EFIVARFSNOW=(%S+)")
    if opts2 and string.match(opts2, "^rw") then
      runtime_writable = true
      tio.echo("\r\n>>> efivarfs remounted rw - running the strict write test <<<\r\n")
    elseif novar ~= "0" then
      runtime_absent = true
      tio.echo("\r\n>>> runtime route ABSENT: firmware exposes no runtime " ..
               "SetVariable, so efivarfs cannot be made writable <<<\r\n")
    else
      fail("efivarfs is mounted read-only (" .. opts .. ") and would not " ..
           "remount rw, but the firmware gave no runtime-SetVariable reason - " ..
           "so this is neither a closed route nor a testable one, and a " ..
           "refused write here would prove nothing about the key database")
    end
  end

  if runtime_absent then
    tio.echo("\r\n>>> part one: no runtime write interface exists to attack <<<\r\n")
  end

  if runtime_writable then
  -- efivarfs sets the immutable attribute on the authentication variables, and
  -- that attribute alone would refuse the write at the filesystem layer without
  -- the firmware ever being asked. Try to clear it first so the refusal comes
  -- from the variable store rather than from a file flag.
  cmd("chattr -i " .. PK .. " > /tmp/hitl.ci 2>&1; echo 'CHATTRRC''='$?; " ..
      "cat /tmp/hitl.ci", 3000)
  local chattr_rc = string.match(tail, "CHATTRRC=(%d+)")
  if not chattr_rc then
    fail("the chattr step produced no return code - the shell is not running " ..
         "what it is sent, and no later result here can be trusted")
  end

  -- The payload carries the 4-byte little-endian attribute prefix efivarfs
  -- requires (0x27 = NV|BS|RT|AT), so a rejection is not a rejection of a
  -- malformed write.
  --
  -- WHAT THIS SEPARATES AND WHAT IT DOES NOT. A missing prefix and a short
  -- write are excluded: the prefix is present and the payload is written in one
  -- call. When chattr reported 0 the immutable attribute was cleared, so the
  -- refusal came from the variable store. When chattr reported non-zero - no
  -- chattr on the image, or the kernel refusing to clear the flag - this check
  -- does NOT distinguish "efivarfs held the immutable attribute" from "the
  -- firmware refused the SetVariable"; it establishes only that the write did
  -- not land. The hash comparison below is what carries the verdict in that
  -- case, and it is the same comparison either way.
  --
  -- The shell's own error goes to the console rather than to a file: when the
  -- `>` redirection is what fails, the command never runs and a `2>` on it is
  -- never applied, so capturing it would capture nothing.
  cmd("printf '\\047\\000\\000\\000AVOCADOHITLTAMPER' > " .. PK ..
      "; echo 'WRITERC''='$?", 4000)
  local write_rc = string.match(tail, "WRITERC=(%d+)")
  if not write_rc then
    fail("the write attempt produced no return code - the command did not run, " ..
         "so nothing was offered to the variable store and nothing was refused")
  end
  if write_rc == "0" then
    fail("the runtime write to PK SUCCEEDED (chattr rc " .. chattr_rc .. ") - " ..
         "the key database is editable from userspace and the enrolment is worthless")
  end
  tio.echo("\r\n>>> runtime write refused (rc " .. write_rc .. ", chattr rc " ..
           chattr_rc .. ") <<<\r\n")

  -- A refused write is not enough on its own: a partial write that failed late
  -- could still have truncated or altered the variable.
  local size1, hash1 = probe_pk()
  if not size1 then
    fail("PK no longer reads back after the refused write - it was damaged, " ..
         "which is a failure of the same requirement")
  end
  if size1 ~= size0 or hash1 ~= hash0 then
    fail("PK CHANGED across the refused write: was " .. size0 .. "/" .. hash0 ..
         ", now " .. size1 .. "/" .. hash1)
  end
  tio.echo("\r\n>>> part one: write refused, PK unchanged <<<\r\n")
  end

  ---------------------------------------------------------------- part two ---

  cmd("reboot", 3000)
  if not reach_prompt(240) then
    fail("board did not return to the U-Boot prompt after the reboot - part " ..
         "two did not run")
  end

  -- Liveness off output the BOARD produces, never off a string this script sent.
  cmd("version", 1500)
  if not saw("U%-Boot") then fail("no version banner - console not actually live") end

  -- The device comes from the board's own environment, the same way every other
  -- U-Boot step in this file resolves it. The PARTITION does not: ${bootpart}
  -- is boot-a, which carries the fitImage and the dtb, while the variable store
  -- lives on the EFI system partition. Those were the same partition on the
  -- layout this mode was written against and are not on the current one.
  --
  -- Resolved by NAME rather than by index, because the index does not hold
  -- still - this card went from 8 partitions to 10 inside two days, and the
  -- position of everything after boot-b moved with it. A hardcoded number would
  -- pass today by pointing at the right partition and later pass by pointing at
  -- the wrong one, which is worse than failing.
  cmd("part number ${devtype} ${devnum} esp espp; echo 'ESPPART''='${espp}", 4000)
  local esppart = string.match(tail, "ESPPART=(%S+)")
  if not esppart or esppart == "" then
    fail("could not resolve a partition named 'esp' on the boot medium - the " ..
         "variable store cannot be located, so part two cannot run")
  end

  cmd("fatls ${devtype} ${devnum}:${espp}", 4000)
  if not saw("file%(s%)") then
    fail("could not list the ESP (partition " .. esppart .. ") - part two cannot run")
  end
  if not saw("ubootefi%.var") then
    fail("no ubootefi.var on the ESP (partition " .. esppart .. "), so there " ..
         "is no store to substitute or delete and part two cannot run")
  end
  if not saw("advstore%.var") then
    fail("no advstore.var on the ESP (partition " .. esppart .. ") - the rival " ..
         "variable store is staged there by avocado-stone under " ..
         "boot-integrity-poc, so this card predates that change or was flashed " ..
         "from a token-absent build. Reflash; without it only the weaker " ..
         "absent-store leg can run")
  end

  ------------------------------------------------------ part two-a: override ---
  --
  -- Substitute a WELL-FORMED rival store that names PK with a different
  -- certificate, and confirm the compiled-in seed still wins.
  --
  -- This is the leg that tests precedence. Deleting the store (part two-b below)
  -- only shows the seed is used when no file is there, which any firmware with
  -- no precedence rule whatsoever would also pass. The claim worth checking is
  -- that a store which IS present and DOES collide loses anyway.
  --
  -- Why a properly-packed rival and not a corrupted one: efi_var_restore()
  -- rejects a bad magic or CRC outright, which puts us straight back on the
  -- absent-store case wearing a disguise. gen-efi-seed.sh packs this one with
  -- the same packer as the real seed and refuses to emit it if it comes out
  -- byte-identical.
  --
  -- Expected to pass by construction rather than by luck: the file-store path is
  -- efi_var_restore(buf, safe=false), and that branch skips every variable whose
  -- efi_auth_var_get_type() is not EFI_AUTH_VAR_NONE - PK, KEK, db and dbx are
  -- all of them. So this leg is a regression guard on that filter across a
  -- firmware bump, not a discovery. If it ever fails, the enrolled key database
  -- is replaceable by anyone who can write the boot medium and every other
  -- assertion in this mode is vacuous.

  -- A scratch address from the board's own environment rather than a literal.
  -- The sent command is `printenv <name>` with no `=`, so the console echoing it
  -- back cannot satisfy a pattern that requires one.
  --
  -- `loadaddr` is tried first and is NOT guaranteed to exist: the board sets
  -- CONFIG_SYS_LOAD_ADDR, which common/board_r.c reads as a FALLBACK
  -- (env_get_ulong("loadaddr", 16, image_load_addr)), so the compiled default
  -- can be in force with no environment variable of that name at all. Falling
  -- back to image_addr keeps this on a board-supplied address either way rather
  -- than hardcoding one here, which is the thing that would pass today and
  -- silently write somewhere wrong after a memory-map change.
  cmd("printenv loadaddr", 1500)
  local scratch = string.match(tail, "loadaddr=(0?x?%x+)") and "${loadaddr}" or nil

  if not scratch then
    -- image_addr is set by the board's own boot script, which is why it is run
    -- first. signed_payload_refused relies on the same variable from the same
    -- source, so this introduces no new assumption.
    cmd("run avocado_boot_init", 1500)
    cmd("printenv image_addr", 1500)
    if string.match(tail, "image_addr=(0?x?%x+)") then
      scratch = "${image_addr}"
    end
  end

  if not scratch then
    fail("the environment defines neither loadaddr nor image_addr, so there is " ..
         "no board-supplied scratch address to stage the rival store at - " ..
         "part two-a cannot run")
  end
  tio.echo("\r\n>>> staging the rival store at " .. scratch .. " <<<\r\n")

  -- BACK THE REAL STORE UP FIRST, before anything overwrites it.
  --
  -- This leg replaces the board's live variable store with an adversarial one,
  -- and nothing used to put the real one back - not on the success path, not on
  -- any of the fail() paths between here and the delete leg. So a run that
  -- failed midway left the board with a rival PLATFORM KEY installed as its
  -- live store, and even a clean run left the card with no store at all. That
  -- matters most on precisely the firmware this leg exists to catch a
  -- regression on: one where the file store is no longer filtered, i.e. where
  -- the rival PK would actually take.
  --
  -- The backup lives on the ESP because it has to survive the resets this leg
  -- performs; a copy in RAM does not.
  cmd("load ${devtype} ${devnum}:${espp} " .. scratch .. " ubootefi.var", 8000)
  if not saw("bytes read") then
    fail("the real ubootefi.var did not load from the ESP, so it cannot be " ..
         "backed up and this leg would have no way to put it back")
  end
  cmd("fatwrite ${devtype} ${devnum}:${espp} " .. scratch ..
      " ubootefi.var.bak ${filesize}", 8000)
  if saw("Unknown command") then
    fail("fatwrite is unavailable on this firmware (CONFIG_FAT_WRITE), so the " ..
         "override leg cannot run - do not record a pass from the delete leg alone")
  end
  if not saw("bytes written") then
    fail("could not back up the real ubootefi.var, so this leg will not be able " ..
         "to restore it and must not proceed to overwrite it")
  end

  cmd("load ${devtype} ${devnum}:${espp} " .. scratch .. " advstore.var", 8000)
  if not saw("bytes read") then
    fail("advstore.var did not load from the ESP, so nothing was staged to " ..
         "substitute and the override leg would test nothing")
  end
  -- Capture the rival's own length, so the write can be checked against it
  -- rather than against the word "written".
  local adv_bytes = string.match(tail, "(%d+)%s+bytes read")

  -- ${filesize} is set by the load above, so the write length is the file's own
  -- rather than a number spelled here that could drift from it.
  cmd("fatwrite ${devtype} ${devnum}:${espp} " .. scratch ..
      " ubootefi.var ${filesize}", 8000)
  if not saw("bytes written") then
    fail("the rival store was not written over ubootefi.var, so the real store " ..
         "is still in place and the override leg would test nothing")
  end

  -- A SHORT write is the dangerous success. U-Boot rejects a store whose length
  -- or CRC does not check out, so a truncated rival is discarded at init and the
  -- compiled-in seed stays authoritative - PK is unchanged, and this leg records
  -- a precedence PASS having actually only re-run the absent-store case it was
  -- written to escape. Compare the byte count the board reports against the
  -- rival's own size rather than accepting the word "written".
  local written = string.match(tail, "(%d+)%s+bytes written")
  if not written then
    fail("fatwrite reported no byte count, so the rival store's persistence " ..
         "cannot be confirmed and a truncated write would read as a pass")
  end
  if adv_bytes and written ~= adv_bytes then
    fail("fatwrite wrote " .. written .. " bytes but advstore.var is " ..
         adv_bytes .. " - a short write leaves a store U-Boot discards for bad " ..
         "length or CRC, which would silently reduce this leg to the " ..
         "absent-store case while reporting a precedence pass")
  end
  tio.echo("\r\n>>> rival PK store written over ubootefi.var on the ESP (" ..
           written .. " bytes) <<<\r\n")

  cmd("reset", 500)
  if not await_login(240) then
    fail("board did not reach a login prompt with the rival store in place")
  end
  login_root()

  local size_ov, hash_ov = probe_pk()
  if not size_ov then
    fail("PK does not read back with the rival store in place - the enrolled " ..
         "key database was displaced by a file on the boot medium, which is the " ..
         "failure this whole mode exists to detect")
  end
  -- Compared against the hash taken before ANY tamper. Comparing against a
  -- re-read would pass on a wholesale substitution, since a substituted PK
  -- hashes consistently with itself.
  if size_ov ~= size0 or hash_ov ~= hash0 then
    fail("PK CHANGED after substituting a rival store: was " .. size0 .. "/" ..
         hash0 .. ", now " .. size_ov .. "/" .. hash_ov .. " - the on-medium " ..
         "file store OVERRODE the compiled-in seed, so the enrolled keys can be " ..
         "replaced by anyone who can write the card")
  end
  tio.echo("\r\n>>> part two-a: rival store ignored, PK unchanged <<<\r\n")

  ------------------------------------------------------ part two-b: absence ---
  --
  -- The weaker leg, kept because it covers a different failure: the seed being
  -- used at all when no file store is present. Runs second so the substitution
  -- above is exercised against a real store rather than against the rival this
  -- leg would have deleted.

  cmd("reboot", 3000)
  if not reach_prompt(240) then
    fail("board did not return to the U-Boot prompt after part two-a - the " ..
         "absent-store leg did not run")
  end
  cmd("version", 1500)
  if not saw("U%-Boot") then fail("no version banner - console not actually live") end

  -- Re-resolved rather than reused: the variable was set before a reboot, and
  -- carrying a stale value across one is how a check comes to address the wrong
  -- partition.
  cmd("part number ${devtype} ${devnum} esp espp; echo 'ESPPART''='${espp}", 4000)
  if not string.match(tail, "ESPPART=(%S+)") then
    fail("could not re-resolve the esp partition after the reboot - the " ..
         "absent-store leg cannot run")
  end

  cmd("fatrm ${devtype} ${devnum}:${espp} ubootefi.var", 4000)
  if saw("Unknown command") then
    fail("fatrm is unavailable on this firmware - the offline half cannot run")
  end

  -- Confirm the delete off a tail that no longer holds the fatrm command line.
  -- That line contains the filename, so a presence match against it would be
  -- satisfied by the console's echo rather than by the directory. `cmd` clears
  -- the tail before writing, and the fatls it sends does not name the file.
  cmd("fatls ${devtype} ${devnum}:${espp}", 4000)
  if not saw("file%(s%)") then
    fail("could not re-list the ESP, so the delete is unconfirmed - " ..
         "the absent-store leg did not run")
  end
  if saw("ubootefi%.var") then
    fail("ubootefi.var is still on the boot partition after fatrm - the delete " ..
         "did not happen, so the offline half was never exercised")
  end
  tio.echo("\r\n>>> variable store deleted from the boot medium <<<\r\n")

  cmd("reset", 500)
  if not await_login(240) then
    fail("board did not reach a login prompt with the variable store deleted")
  end
  login_root()

  local size2, hash2 = probe_pk()
  if not size2 then
    fail("PK is GONE after deleting the variable store - the key database came " ..
         "from the editable file store, not from the seed compiled into the " ..
         "bootloader, and deleting a file on a FAT partition disarms Secure Boot")
  end
  -- Presence alone would pass on a substituted PK, so the comparison is against
  -- the hash recorded before the FIRST tamper.
  if size2 ~= size0 or hash2 ~= hash0 then
    fail("PK is present but DIFFERENT after deleting the variable store: was " ..
         size0 .. "/" .. hash0 .. ", now " .. size2 .. "/" .. hash2 ..
         " - the file store can override the compiled-in seed")
  end

  ------------------------------------------------------------- restore -------
  --
  -- Put the board back the way it was found. Both legs above are destructive to
  -- the ESP - two-a overwrites ubootefi.var with the rival, two-b deletes it -
  -- and neither used to undo itself, so a passing run left the card with no
  -- variable store and the rival still sitting beside it. The next run then
  -- failed at its own precondition ("no ubootefi.var on the ESP"), and the
  -- recovery was documented nowhere.
  --
  -- This runs after the verdict-deciding comparison, so a restore failure
  -- cannot manufacture a pass; it can only report that cleanup did not finish.
  cmd("reboot", 3000)
  if not reach_prompt(240) then
    fail("board did not return to the U-Boot prompt for the restore - the " ..
         "assertions held, but the ESP is left with no ubootefi.var and the " ..
         "backup still at ubootefi.var.bak; restore it before the next run")
  end
  cmd("part number ${devtype} ${devnum} esp espp; echo 'ESPPART''='${espp}", 4000)
  if not string.match(tail, "ESPPART=(%S+)") then
    fail("could not re-resolve the esp partition for the restore - the ESP is " ..
         "left with no ubootefi.var and the backup still at ubootefi.var.bak")
  end
  -- Re-run the board's boot init before reusing the scratch address. When
  -- `scratch` resolved to ${image_addr} it was set by avocado_boot_init, and the
  -- two reboots since then reloaded the environment - so the variable can be
  -- empty here, which would make the load address expand to nothing. Harmless
  -- when scratch is ${loadaddr}, which U-Boot's own default environment carries.
  cmd("run avocado_boot_init", 1500)
  cmd("load ${devtype} ${devnum}:${espp} " .. scratch .. " ubootefi.var.bak", 8000)
  if not saw("bytes read") then
    fail("the backup ubootefi.var.bak did not load, so the real variable store " ..
         "cannot be restored; the card is left without one")
  end
  cmd("fatwrite ${devtype} ${devnum}:${espp} " .. scratch ..
      " ubootefi.var ${filesize}", 8000)
  if not saw("bytes written") then
    fail("could not restore ubootefi.var from the backup; the card is left " ..
         "without a variable store")
  end
  tio.echo("\r\n>>> real variable store restored from ubootefi.var.bak <<<\r\n")

  -- The verdict names which runtime outcome actually occurred. A single wording
  -- covering both would report a refusal that never happened on a platform with
  -- no interface to refuse it, which is the specific overclaim this mode exists
  -- to avoid making.
  local runtime_verdict
  if runtime_absent then
    runtime_verdict = "no runtime write interface exists (firmware exposes no " ..
                      "SetVariableRT, efivarfs cannot be made writable), so the " ..
                      "runtime route is closed by absence rather than by refusal"
  else
    runtime_verdict = "runtime write to PK refused with PK unchanged"
  end

  -- Both offline legs are named, because they are different claims and only the
  -- first is about precedence. A verdict citing the deletion alone reads as
  -- "the seed wins" when it only shows "the seed is used when nothing competes".
  pass(runtime_verdict .. "; a well-formed rival store naming a DIFFERENT PK " ..
       "was written over ubootefi.var on the ESP and the enrolled PK did not " ..
       "change, and the same PK also survived deleting the store outright - the " ..
       "compiled-in seed beats an on-medium store rather than merely filling in " ..
       "for a missing one")
end

fail("unknown HARNESS_MODE '" .. MODE .. "'")
