-- HITL mode: keydb_immutable
--
-- Loaded by imx93-harness.lua via dofile once HARNESS_MODE selects it, so
-- everything the shared runtime defines (cmd, saw, fail, pass, reach_prompt,
-- await_login, login_root, watch, latched_saw, esp_has, settle, and the tail
-- buffer itself) is already in scope here and is deliberately global there.

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
-- Whole-entry, not substring. This is the same prefix trap as the delete
-- check below and it fails the other way round: a leftover ubootefi.var.bak
-- from an interrupted run would satisfy a substring match and let the leg
-- proceed believing it had a real store to back up and substitute.
if not esp_has("ubootefi.var") then
  fail("no ubootefi.var on the ESP (partition " .. esppart .. "), so there " ..
       "is no store to substitute or delete and part two cannot run")
end
if not esp_has("advstore.var") then
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
--
-- The backup-or-recover decision is made from WHAT IS ON THE ESP, never from
-- whether ubootefi.var happens to load, and that distinction is the whole
-- safety property. A run interrupted between the substitution and the final
-- restore leaves ubootefi.var holding the RIVAL while the genuine store
-- survives only in ubootefi.var.bak. Keying off "does ubootefi.var load"
-- would read that rival as the real store, copy it over the only genuine
-- copy, and then "restore" the rival at the end - turning one interrupted
-- run into permanent loss of the board's variable store, recoverable only by
-- reflashing. An existing backup is therefore always restored FROM and never
-- written to.
cmd("fatls ${devtype} ${devnum}:${espp}", 4000)
if not saw("file%(s%)") then
  fail("could not list the ESP before deciding whether to back up or recover " ..
       "the variable store, so this leg cannot start safely")
end

if esp_has("ubootefi.var.bak") then
  tio.echo("\r\n>>> backup from an earlier run present: recovering from it, " ..
           "not overwriting it <<<\r\n")
  cmd("load ${devtype} ${devnum}:${espp} " .. scratch .. " ubootefi.var.bak", 8000)
  if not saw("bytes read") then
    fail("ubootefi.var.bak is listed on the ESP but does not load, so the " ..
         "genuine variable store can be neither recovered nor safely " ..
         "replaced - reflash the board")
  end
  cmd("fatwrite ${devtype} ${devnum}:${espp} " .. scratch ..
      " ubootefi.var ${filesize}", 8000)
  if saw("Unknown command") then
    fail("fatwrite is unavailable on this firmware (CONFIG_FAT_WRITE), so the " ..
         "override leg cannot run - do not record a pass from the delete leg alone")
  end
  if not saw("bytes written") then
    fail("could not write the recovered store back to ubootefi.var - reflash " ..
         "the board")
  end
else
  cmd("load ${devtype} ${devnum}:${espp} " .. scratch .. " ubootefi.var", 8000)
  if not saw("bytes read") then
    fail("the real ubootefi.var did not load from the ESP and there is no " ..
         "ubootefi.var.bak to recover it from, so this leg has nothing to " ..
         "back up and no way to put anything back")
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
end

-- Re-read whatever now sits at ubootefi.var, so the substitution starts from
-- a store known to be readable rather than one assumed to be. Both branches
-- above end with a write, and `bytes written` says a write was accepted, not
-- that what landed can be read back.
cmd("load ${devtype} ${devnum}:${espp} " .. scratch .. " ubootefi.var", 8000)
if not saw("bytes read") then
  fail("ubootefi.var does not load after the backup/recovery step, so the " ..
       "store on the ESP is not usable and part two-a cannot run")
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
if esp_has("ubootefi.var") then
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

-- Retire the backup now that it has served its purpose, so the ESP is left
-- as this leg found it.
--
-- Leaving it behind would make every later run take the recover-from-backup
-- branch above instead of the ordinary backup branch, and that branch writes
-- the backup OVER ubootefi.var. The copy would then get staler on every run
-- while remaining authoritative, so any UEFI variable legitimately written
-- between runs - by uefi_var_persists, or by the firmware itself - would be
-- silently reverted by the next keydb_immutable. A transient file that
-- outlives its transaction stops being a backup and becomes a rollback.
--
-- Deliberately NOT fatal. The store is already restored by this point, which
-- is the property that matters; a leftover backup costs a stale-revert on the
-- next run, not a broken board, and failing here would convert a successful
-- security assertion into a FAIL over cleanup.
cmd("fatrm ${devtype} ${devnum}:${espp} ubootefi.var.bak", 4000)
cmd("fatls ${devtype} ${devnum}:${espp}", 4000)
if esp_has("ubootefi.var.bak") then
  tio.echo("\r\n>>> WARNING: ubootefi.var.bak could not be removed. The store " ..
           "is restored, but the next run will recover from this copy rather " ..
           "than take a fresh backup <<<\r\n")
end

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
