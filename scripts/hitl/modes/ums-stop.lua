-- HITL mode: ums_stop
--
-- Loaded by imx93-harness.lua via dofile once HARNESS_MODE selects it, so
-- everything the shared runtime defines (cmd, saw, fail, pass, reach_prompt,
-- await_login, login_root, watch, latched_saw, esp_has, settle, and the tail
-- buffer itself) is already in scope here and is deliberately global there.

-- Stop an export this script is not holding: the caller's cleanup path, and the
-- way to recover a board left exporting by a previous run. Idempotent - Ctrl-C
-- at an idle prompt does nothing, so running it on a board that is not
-- exporting is safe and still confirms the prompt is reachable.
if not reach_prompt(60) then
  fail("could not reach the U-Boot prompt to stop an export")
end
pass("export stopped; board is at the U-Boot prompt")
