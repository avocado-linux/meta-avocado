-- HITL mode: boot_integrity_report
--
-- Loaded by imx93-harness.lua via dofile once HARNESS_MODE selects it, so
-- everything the shared runtime defines (cmd, saw, fail, pass, reach_prompt,
-- await_login, login_root, watch, latched_saw, esp_has, settle, and the tail
-- buffer itself) is already in scope here and is deliberately global there.

-- Boot, then read the record the on-device reporter publishes and check it
-- carries BOTH halves. Enforcement alone is the failure this whole change
-- exists to prevent, so a record with one and not the other fails here rather
-- than reaching a fleet view.
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
