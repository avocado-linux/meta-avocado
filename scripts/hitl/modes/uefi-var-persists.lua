-- HITL mode: uefi_var_persists
--
-- Loaded by imx93-harness.lua via dofile once HARNESS_MODE selects it, so
-- everything the shared runtime defines (cmd, saw, fail, pass, reach_prompt,
-- await_login, login_root, watch, latched_saw, esp_has, settle, and the tail
-- buffer itself) is already in scope here and is deliberately global there.

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

-- Continue to a real boot so the record can name the image, rather than
-- recording `none`. This mode's own assertion is already decided by this
-- point; everything below is evidence collection, not part of the test.
--
-- Every other identified record is a rootfs digest, so this stays consistent
-- with that rather than inventing a bootloader-binary identity nothing else
-- tracks - and check-result.sh's staleness comparison needs no changes to
-- read it. Booting the slot the board already has selected is what the write
-- above actually exercised, so the identity describes the same run.
cmd("reset", 500)
if not await_login(240) then
  fail("the persistence assertion already passed, but the board did not " ..
       "reach a login prompt on the follow-up boot, so this record cannot " ..
       "name its image - re-run")
end
login_root()

pass("UEFI variable written, survived a reset, and read back. " ..
     "NOTE: this proves PERSISTENCE only. The PoC store is a file on a FAT " ..
     "partition and is not tamper-resistant.")
