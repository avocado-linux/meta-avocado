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
local function reach_prompt(deadline_s)
  local deadline = os.time() + deadline_s
  local window_seen = false
  tail = ""
  while os.time() < deadline do
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

fail("unknown HARNESS_MODE '" .. MODE .. "'")
