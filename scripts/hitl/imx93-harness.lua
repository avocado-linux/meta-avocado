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
ARG = os.getenv("HARNESS_ARG") or ""
local ID_FILE = os.getenv("HARNESS_ID_FILE") or ""
local TAIL_MAX = 24000

tail = ""

-- Board-reported identity of the software this run actually exercised, written
-- to HARNESS_ID_FILE for imx93-harness.sh to stamp into the record.
--
-- The record already names a COMMIT, and under this project's reproducible
-- builds a commit pins the build content exactly. What it could not say is
-- whether the BOARD is carrying that build. Every guard downstream - tree
-- state, ancestor-of-HEAD, --since - reads host-side git, and none of them can
-- see a reflash. That is not a hypothetical gap: seven records were carried
-- across two reflashes during this work and every one went on validating, and
-- an env_lockdown FAIL was chased as a code defect when the board was simply
-- running a different image.
--
-- Three states, and they are not interchangeable:
--   <16 hex>  a digest the board computed and reported
--   none      the run never reached a Linux shell, so there was nothing to ask
--   unknown   a shell was reached and no digest came back
-- check-result.sh accepts the first two and rejects the third, on the same
-- principle as the tree field: failing to ask is not an answer.
--
-- Four of the six assert modes report a digest. env_lockdown and slot_boots
-- take a login they do not otherwise need, purely so their records can be
-- checked; boot_integrity_report and keydb_immutable already had one.
--
-- The remaining two are `none` BY CONSTRUCTION and the gap they leave is OPEN:
-- uefi_var_persists never leaves U-Boot, and signed_payload_refused asserts
-- that the board does not boot at all, so neither can be asked what it is
-- running from a shell. Their records are therefore invisible to the staleness
-- check in check-result.sh and will keep validating across a reflash.
--
-- What blocks closing it is NOT capability. The board can hash from the U-Boot
-- prompt - imx93_11x11_frdm_defconfig-sd/.config carries CONFIG_CMD_HASH=y, so
-- `hash sha256` is available, and an earlier version of this comment claimed
-- otherwise. It is that a U-Boot-side digest would measure a DIFFERENT quantity
-- from the Linux-side one below: the boot payload rather than the rootfs
-- payload. Recording both under one field would make every U-Boot record
-- compare unequal to every Linux record, so the staleness check would reject
-- every mode against every other - a guard that fires on everything is a guard
-- that gets disabled. Closing this properly means a two-part identity compared
-- component-wise, which is a design change and not a line of Lua.
--
-- The other reason not to reach for the obvious file: `ubootefi.var` is the
-- MUTABLE store, and uefi_var_persists writes to it as its whole assertion, so
-- hashing it would produce an identity that changes because the test ran.
local IMAGE_ID = "none"

-- Written from pass() and fail() so it lands on BOTH verdicts. A FAIL is the
-- case that most needs it - the wrong-image run above recorded FAIL, and the
-- identity is what would have named the cause in one line.
--
-- Every failure here is silent by design. This is evidence about the run, not
-- part of the assertion, so a missing file must not turn a genuine PASS into a
-- FAIL; the empty value it leaves behind is read as `unknown` by the caller
-- and rejected there, which is where the reader can act on it.
local function write_image_id()
  if ID_FILE == "" then return end
  local f = io.open(ID_FILE, "w")
  if not f then return end
  f:write(IMAGE_ID .. "\n")
  f:close()
end

-- Markers are LATCHED as they stream past, not looked for in the tail at the
-- end. A full boot is roughly 100 KB and the tail is bounded, so an early marker
-- like "Booting B" is evicted long before "login:" arrives - asking for both to
-- coexist in the buffer is a test that can never pass on a long boot. This is a
-- real defect that was written, run, and observed failing here before being
-- fixed; keep the latch.
local latched = {}
local watched = {}

function watch(p) watched[p] = true; latched[p] = latched[p] or false end
function latched_saw(p) return latched[p] == true end

local function absorb(c)
  tail = tail .. c
  for p, _ in pairs(watched) do
    if not latched[p] and string.match(tail, p) then latched[p] = true end
  end
  if #tail > TAIL_MAX then tail = string.sub(tail, -TAIL_MAX) end
end

function saw(p) return string.match(tail, p) ~= nil end

-- Match a filename in a `fatls` listing as a WHOLE entry.
--
-- `ubootefi.var` is a prefix of `ubootefi.var.bak`, the backup the precedence
-- leg writes, so a plain substring match is satisfied by the backup and reports
-- the real store as present when it is gone. That is measured, not feared: on
-- the first run after the backup was introduced it turned a working offline
-- delete into a FAIL reading "the delete did not happen", and the ESP listing
-- in the same log showed three files with ubootefi.var plainly absent. The
-- message blamed the board for a defect in the check.
--
-- fatls prints `<size>   <name>\r\n`, so requiring a line terminator directly
-- after the name is what makes the entry whole. The dots are escaped here so
-- callers pass a filename rather than a Lua pattern - the raw-pattern form is
-- what let the prefix bug in unnoticed.
function esp_has(name)
  local escaped = name:gsub("%.", "%%.")
  return string.match(tail, escaped .. "[\r\n]") ~= nil
end

-- Sleep `ms` of REAL time, draining whatever arrives. The short read timeout is
-- only so a quiet line does not stall; the msleep is what costs the time.
function settle(ms)
  local left = ms
  while left > 0 do
    tio.msleep(100)
    left = left - 100
    local c = tio.read(4096, 20)
    if c then absorb(c) end
  end
end

function fail(msg)
  write_image_id()
  tio.echo("\r\nRESULT: FAIL - " .. msg .. "\r\n")
  tio.echo("---- image ---- " .. IMAGE_ID .. "\r\n")
  tio.echo("---- tail ----\r\n" .. tail .. "\r\n--------------\r\n")
  os.exit(1)
end

function pass(msg)
  write_image_id()
  tio.echo("\r\nRESULT: PASS - " .. msg .. " [image " .. IMAGE_ID .. "]\r\n")
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
function reach_prompt(deadline_s)
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

function cmd(line, settle_ms)
  tail = ""
  tio.write(line .. "\r\n")
  tio.msleep(300)
  settle(settle_ms or 1200)
end

-- Wait for the board to boot through to userspace without sending anything.
-- Passive by construction: a send here would interrupt the autoboot it is
-- waiting on.
function await_login(deadline_s)
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
-- Ask the board what it is running. Called from the shared login path below so
-- every mode that reaches a shell stamps an identity without opting in - a mode
-- that had to remember to call this is a mode that will eventually forget.
--
-- Scoped to the rootfs payload these assertions are ABOUT - the reporter, the
-- corroboration reference it compares against, and the descriptor it is not
-- allowed to trust - and NOT to the whole image. State the limit rather than
-- imply otherwise: a reflash changing only the bootloader leaves this digest
-- identical, so agreement across records does not prove the bootloader is
-- unchanged. Two things it does close, both of which have already cost a cycle
-- here: a rootfs fix committed and flashed while older records went on
-- validating, and a verdict whose image nobody could name after the fact.
--
-- The U-Boot version banner is the obvious alternative and it does not work.
-- SOURCE_DATE_EPOCH pins its build timestamp, so two bootloaders built from
-- different trees print the same banner, byte for byte - measured here as
-- `(Jun 02 2026 - 15:03:39 +0000)` across every build in this branch. A
-- content digest is the only thing that moves when the content does.
--
-- Every file is tested readable BEFORE the digest is taken, and that is the
-- load-bearing half. `sha256sum a b c 2>/dev/null | sha256sum` over three
-- absent files hashes an EMPTY stream and returns a perfectly well-formed
-- digest that means "nothing was found" - a false identity that would compare
-- equal across every image missing the payload. No marker at all is the
-- correct output for that case, and it lands on `unknown`.
local function capture_image_id()
  -- Only the reporter is installed on every build. boot-integrity.bb gates
  -- db.der.sha256 and the descriptor behind AVOCADO_BOOT_INTEGRITY_POC, so
  -- REQUIRING all three made a token-absent image unidentifiable - the digest
  -- came back empty, IMAGE_ID landed on `unknown`, and check-result.sh rejected
  -- it. That is not a corner: task 8.5 verifies the default path with
  -- `check-result.sh slot_boots a`, and slot_boots reaches a shell, so demanding
  -- the PoC-only files made that task's verify unsatisfiable on the very build
  -- flavour it exists to check.
  --
  -- So hash the files that ARE there, and keep requiring the one that is always
  -- there. That last requirement is what preserves the empty-input guard: with
  -- no readable file at all, `cat` hashes an empty stream and returns a
  -- well-formed digest meaning "nothing found", which would compare equal
  -- across every image missing the payload.
  --
  -- The two flavours land in different digest namespaces rather than colliding,
  -- because the hashed BYTES differ - one stream is the reporter alone, the
  -- other is the reporter followed by two more files. A token-absent record and
  -- a PoC record therefore read as different images, which is what they are.
  --
  -- Argument order is preserved exactly, so a PoC image hashes the same three
  -- files in the same sequence as before this branch existed and records made
  -- either side of it stay comparable.
  --
  -- Be honest about what the fallback buys: on a token-absent image the digest
  -- covers one script, so two default builds differing anywhere else compare
  -- equal. It identifies the payload under assertion, not the image.
  local A = "/usr/libexec/boot-integrity/boot-integrity-report.sh"
  local B = "/usr/libexec/boot-integrity/db.der.sha256"
  local C = "/etc/avocado/boot-integrity-store"
  cmd("test -r " .. A .. " && { set -- " .. A .. "; " ..
      "test -r " .. B .. " && set -- \"$@\" " .. B .. "; " ..
      "test -r " .. C .. " && set -- \"$@\" " .. C .. "; " ..
      "echo PAYLOAD-ID:$(cat \"$@\" | sha256sum | cut -c1-16); }", 4000)

  -- Anchored to EXACTLY 16 hex characters, which is what makes the shell's own
  -- echo of the command line unable to satisfy it: there, `PAYLOAD-ID:` is
  -- followed by `$`, so the pattern cannot match the echo and go on to report
  -- an identity for a command that never ran.
  local id = string.match(tail, "PAYLOAD%-ID:(%x%x%x%x%x%x%x%x%x%x%x%x%x%x%x%x)")
  IMAGE_ID = id or "unknown"
end

function login_root()
  cmd("root", 4000)
  if saw("avocado%-imx93%-frdm:~#") then
    capture_image_id()
    return
  end

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


-- Mode bodies live one per file under modes/, and the split is not tidiness.
-- The file is the unit the review tooling bounds context by, and this one had
-- grown past that bound: a cross-vendor review reported
-- `truncated_inputs:file_contents`, keeping 64071 of 65507 bytes, so the tail
-- of the largest mode was read by no reviewer while the run still returned
-- findings for everything else. A file per mode is what keeps each one
-- reviewable in full as modes are added.
--
-- The shared runtime above is global on purpose. A dofile'd chunk cannot see
-- the caller's locals, so the thirteen names a mode body actually uses are
-- declared global and the remaining nine stay local - the split was made
-- against that measured list rather than by globalising everything.
local MODE_FILES = {
  env_lockdown = "env-lockdown.lua",
  slot_boots = "slot-boots.lua",
  uefi_var_persists = "uefi-var-persists.lua",
  ums_hold = "ums-hold.lua",
  ums_stop = "ums-stop.lua",
  boot_integrity_report = "boot-integrity-report.lua",
  signed_payload_refused = "signed-payload-refused.lua",
  keydb_immutable = "keydb-immutable.lua",
}

-- Set by imx93-harness.sh, which knows where it lives. Deriving it here is not
-- an option: tio does not populate `arg` for a --script-file chunk, so the
-- script cannot find its own directory, and a relative path would resolve
-- against whatever cwd the caller happened to have.
local LIB_DIR = os.getenv("HARNESS_LIB_DIR") or ""
if LIB_DIR == "" then
  fail("HARNESS_LIB_DIR is unset, so the mode files cannot be located. " ..
       "imx93-harness.sh sets it; this chunk is not meant to be run directly.")
end

local mode_file = MODE_FILES[MODE]
if not mode_file then
  fail("unknown HARNESS_MODE '" .. MODE .. "'")
end
dofile(LIB_DIR .. "/modes/" .. mode_file)
