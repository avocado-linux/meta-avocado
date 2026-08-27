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

  -- Passwordless root on the bringup image; the getty says so itself.
  cmd("root", 4000)
  if not saw("avocado%-imx93%-frdm:~#") then fail("did not reach a root shell") end

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

  -- efivarfs never appeared, so the kernel was not entered through the EFI stub
  -- and the boot path change did not take.
  if saw("enforcement=unavailable") then
    fail("enforcement is unavailable - efivarfs did not appear, so the EFI hand-off did not take")
  end

  -- The expected result on THIS board, and the direction that matters. Its
  -- SRK_HASH fuse is burned byte-swapped, so AHAB cannot be closed and nothing
  -- anchors the firmware. An indicator reading authenticated is a defect in the
  -- reader, not good news, and must fail rather than be reported as a pass.
  if saw("rot_state=authenticated") then
    fail("root of trust reads authenticated on a board whose AHAB lifecycle is open")
  end

  pass("record carries enforcement, a root-of-trust indicator and a keydb_origin; root of trust is not authenticated")
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
-- STAGING PREREQUISITE. The boot partition must carry `Image.unsigned`: a copy
-- of the unsigned kernel `Image` that the deploy step deliberately leaves
-- byte-identical while signing a separate `Image.signed` for the ESP. Put it
-- there with `--ums-hold` before running this mode. The distinct filename is
-- deliberate - loading a bare `Image` would silently pick up whatever a future
-- manifest happens to stage under that name, and this check must never be
-- satisfied by a file nobody chose.
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

  -- Overwrite image_addr with the UNSIGNED payload, replacing the signed one the
  -- board would otherwise run. Asserting this read is what separates "the
  -- firmware refused it" from "there was nothing to refuse".
  cmd("load ${devtype} ${devnum}:${bootpart} ${image_addr} Image.unsigned", 15000)
  if not saw("bytes read") then
    fail("Image.unsigned did not load from the boot partition - stage the " ..
         "unsigned kernel Image there with --ums-hold first. Nothing was " ..
         "offered to the firmware, so nothing was refused")
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
--   part one, RUNTIME  - a write to PK from a booted root shell is refused and
--                        leaves PK byte-identical;
--   part two, OFFLINE  - deleting the variable store from the boot medium and
--                        resetting leaves the SAME PK in place, because the
--                        seed compiled into the bootloader is authoritative and
--                        the file store cannot override it.
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

  local function login_root()
    cmd("root", 4000)
    if not saw("avocado%-imx93%-frdm:~#") then
      fail("did not reach a root shell - neither half of this mode can run")
    end
  end

  if not reach_prompt(180) then fail("never reached the U-Boot prompt") end
  cmd("reset", 500)
  if not await_login(240) then fail("board did not reach a login prompt") end
  login_root()

  ---------------------------------------------------------------- part one ---

  -- A read-only efivarfs would refuse the write for a reason that has nothing
  -- to do with the key database, and that refusal would read exactly like the
  -- one being tested for. Establish the mount is writable before drawing any
  -- conclusion from a failed write. awk concatenates the two literals, so the
  -- printed key differs from the sent one.
  cmd("awk '$3==\"efivarfs\"{print \"EFIVARFSOPTS\" \"=\" $4}' /proc/mounts", 3000)
  local opts = string.match(tail, "EFIVARFSOPTS=(%S+)")
  if not opts then
    fail("efivarfs is not mounted - there is no runtime variable interface to " ..
         "write to, so part one cannot run")
  end
  if not string.match(opts, "^rw") then
    fail("efivarfs is mounted read-only (" .. opts .. ") - a refused write " ..
         "proves nothing about the key database")
  end

  local size0, hash0 = probe_pk()
  if not size0 then
    fail("PK did not read back from efivarfs - either the key database is not " ..
         "enrolled, or the image carries no wc/sha256sum for the probe to use. " ..
         "Either way there is nothing whose immutability could be tested")
  end
  if size0 == "0" then fail("PK is present but empty - nothing to protect") end
  tio.echo("\r\n>>> PK recorded before any tamper: " .. size0 .. " bytes, " ..
           hash0 .. " <<<\r\n")

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

  ---------------------------------------------------------------- part two ---

  cmd("reboot", 3000)
  if not reach_prompt(240) then
    fail("board did not return to the U-Boot prompt after the reboot - part " ..
         "two did not run")
  end

  -- Liveness off output the BOARD produces, never off a string this script sent.
  cmd("version", 1500)
  if not saw("U%-Boot") then fail("no version banner - console not actually live") end

  -- The device and partition come from the board's own environment, the same
  -- way every other U-Boot step in this file resolves them.
  cmd("fatls ${devtype} ${devnum}:${bootpart}", 4000)
  if not saw("file%(s%)") then
    fail("could not list the boot partition - part two cannot run")
  end
  if not saw("ubootefi%.var") then
    fail("no ubootefi.var on the boot partition, so there is no store to " ..
         "delete and part two cannot run. It must be the ESP the firmware " ..
         "reads its variable file from")
  end

  cmd("fatrm ${devtype} ${devnum}:${bootpart} ubootefi.var", 4000)
  if saw("Unknown command") then
    fail("fatrm is unavailable on this firmware - the offline half cannot run")
  end

  -- Confirm the delete off a tail that no longer holds the fatrm command line.
  -- That line contains the filename, so a presence match against it would be
  -- satisfied by the console's echo rather than by the directory. `cmd` clears
  -- the tail before writing, and the fatls it sends does not name the file.
  cmd("fatls ${devtype} ${devnum}:${bootpart}", 4000)
  if not saw("file%(s%)") then
    fail("could not re-list the boot partition, so the delete is unconfirmed - " ..
         "part two did not run")
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

  pass("runtime write to PK refused with PK unchanged, and the same PK " ..
       "survived deletion of the variable store on the boot medium - the " ..
       "compiled-in seed is authoritative")
end

fail("unknown HARNESS_MODE '" .. MODE .. "'")
