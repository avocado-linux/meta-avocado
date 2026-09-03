-- HITL mode: slot_boots
--
-- Loaded by imx93-harness.lua via dofile once HARNESS_MODE selects it, so
-- everything the shared runtime defines (cmd, saw, fail, pass, reach_prompt,
-- await_login, login_root, watch, latched_saw, esp_has, settle, and the tail
-- buffer itself) is already in scope here and is deliberately global there.

if ARG ~= "a" and ARG ~= "b" then fail("slot_boots needs HARNESS_ARG a or b") end
if not reach_prompt(180) then fail("never reached the U-Boot prompt") end
cmd("env set avocado_boot_slot " .. ARG, 800)
cmd("saveenv", 4000)
local want = (ARG == "a") and "Booting A" or "Booting B"
watch(want)
cmd("reset", 500)
if not await_login(240) then fail("slot " .. ARG .. " did not reach a login prompt") end
if not latched_saw(want) then fail("expected '" .. want .. "' and did not see it") end

-- As in env_lockdown: the login exists to stamp the record with the image,
-- not because the assertion needs a shell. A slot_boots record that cannot
-- name its image is the easiest of all of these to carry across a reflash,
-- since "the slot boots" stays true of images that differ in every other way.
login_root()

pass("slot " .. ARG .. " booted to a login prompt")
