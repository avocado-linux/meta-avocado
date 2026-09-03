# Task 4.3: `avocado-raspberrypi5` is unaffected when `encrypted-var` is not requested

Confirms the third case: a build that does not request `encrypted-var` at all
is unaffected by the deliverability check (task 2.2) existing, regardless of
whether the selected machine has a var-key provider.

## Why `avocado-raspberrypi5`

Raspberry Pi is deliberately the machine with NO var-key provider - the
opposite of task 4.2's `avocado-imx93-frdm`. No `cryptsetup-var.bbappend` or
`FILESEXTRAPATHS:prepend:<machine>` override exists anywhere under
`meta-avocado-raspberrypi/`:

```
$ find -L meta-avocado-raspberrypi -iname "*cryptsetup-var*"
(no output)
```

So `cryptsetup-var.bb`'s `FILESPATH` lookup for `avocado-raspberrypi5` falls
through to the shared, sentinel-carrying
`meta-avocado/recipes-core/cryptsetup-var/files/var-key.sh` - the same
resolution as task 4.1's scratch machine. That is what makes this negative
result meaningful rather than trivial: if `encrypted-var` were requested here,
the check's second gate (sentinel present) would be satisfied, so the only
thing suppressing the check in this build is the first gate - the absent
feature request - not the presence of a provider.

## `encrypted-var` is not in DISTRO_FEATURES for any real machine

```
$ grep -rn "DISTRO_FEATURES.*encrypted-var\|encrypted-var.*DISTRO_FEATURES" meta-avocado --include="*.conf" --include="*.inc" --include="*.bb*" --include="*.yml"
meta-avocado/classes/avocado-security-capabilities.bbclass:59:    if "encrypted-var" in (d.getVar("DISTRO_FEATURES") or "").split():
meta-avocado/classes/avocado-security-capabilities.bbclass:61:            "DISTRO_FEATURES contains encrypted-var, which no longer selects "
meta-avocado/recipes-core/cryptsetup-var/cryptsetup-var.bb:26:    if not bb.utils.contains("DISTRO_FEATURES", "encrypted-var", True, False, d):
meta-avocado/recipes-kernel/linux/avocado-security-kernel.inc:5:# on the encrypted-var / secureboot DISTRO_FEATURES the way the shared
```

The only matches are the two checks themselves reading the variable, plus a
comment - nothing writes `encrypted-var` into `DISTRO_FEATURES` for any real
machine any more. `kas/feature/encrypted-var.yml` was removed by commit
`0f20494c`; `encrypted-var` is now a purely runtime toggle
(`avocado.yaml`'s `var.encrypt`), never a `DISTRO_FEATURES` token, except for
task 4.1's temporary scratch construction which appended it by hand. So a
plain `kas/machine/raspberrypi5.yml` build - no feature overlay - has
`DISTRO_FEATURES` lacking `encrypted-var` by construction, with nothing extra
required to arrange it.

## Command

```
bakar bitbake cryptsetup-var kas/machine/raspberrypi5.yml
```

Run from `/home/tiamarin/repos/work/peridio/meta-avocado/`. Same bare
recipe-build pattern used by tasks 1.2, 4.1, and 4.2 - no feature overlay
appended, since none exists that sets `encrypted-var` any more.

## Result: build succeeds, no refusal

Exit code: `0`.

```
INFO     ✓ parsing recipes complete (42s)  [7182 fresh, cache empty]
✓ parse (42s)  ──  ✓ setscene (4s)  ──  ✓ tasks (13m02s)   14m00s
 45% sstate (498 cached, 603 will build)
kas_build ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 2684/2684 tasks
4 warnings, 0 errors
INFO     ✓ kas_shell_live
INFO     ✓ bitbake_events
EXIT: 0
```

The cooker console log's task summary confirms `cryptsetup-var.bb:do_build`
ran as the final (noexec) task with every prerequisite succeeding:

```
NOTE: Running noexec task 2684 of 2684 (.../meta-avocado/recipes-core/cryptsetup-var/cryptsetup-var.bb:do_build)
NOTE: Tasks Summary: Attempted 2684 tasks of which 979 didn't need to be rerun and all succeeded.
```

## Confirmation the check produced zero side effects, not just no fatal

```
$ grep -in "fatal\|var-key provider\|encrypted-var" build-raspberrypi5/build/tmp/log/cooker/avocado-raspberrypi5/console-latest.log
(no output)
```

Nothing in the full cooker console log mentions `fatal`, `var-key provider`,
or `encrypted-var` - not even a warning. This is the anonymous-python gate in
`cryptsetup-var.bb` (`if not bb.utils.contains("DISTRO_FEATURES",
"encrypted-var", ...): return`) returning immediately, before it ever reaches
the `FILESPATH` resolution or the sentinel read. That distinguishes this
suppression from task 4.2's: there, the machine's own provider satisfied the
second gate cleanly; here, the first gate never lets the check reach the
second one at all, on a machine that would fail it if it did.

The four warnings present in the run are unrelated host/BSP warnings (host
distribution `cachyos` not validated, `BBFILE_PATTERN_cache-classify` with no
matching `.bb` files) - the same warnings every `bakar bitbake` invocation on
this host emits, confirmed absent of any deliverability-related text.

## Cleanup

No scratch machine, kas file, or temporary code was created for this task -
`kas/machine/raspberrypi5.yml` is a pre-existing, permanent part of the repo,
and the build used the existing `build-raspberrypi5/` sibling build directory
from earlier tasks. `git status --short` in `meta-avocado/` is clean except
for this test file.
