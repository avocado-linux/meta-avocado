-- HITL mode: env_lockdown
--
-- Loaded by imx93-harness.lua via dofile once HARNESS_MODE selects it, so
-- everything the shared runtime defines (cmd, saw, fail, pass, reach_prompt,
-- await_login, login_root, watch, latched_saw, esp_has, settle, and the tail
-- buffer itself) is already in scope here and is deliberately global there.

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

-- Nothing in this assertion needs a shell. The login is here purely so the
-- record can name the image the board was running, and this mode is the one
-- that most needs it: its only observed failure was a FAIL recorded against
-- an image built without CONFIG_ENV_WRITEABLE_LIST, and it was chased as a
-- code defect for a full cycle because the record could not say which image
-- had produced it.
--
-- It is a hard login, not a best-effort one. An image without passwordless
-- root cannot be identified, and login_root names that cause precisely; a
-- silent skip would hand back the unattributable PASS this exists to end.
login_root()

pass("saved bootcmd rejected, saved avocado_boot_slot honoured, board booted")
