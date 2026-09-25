#!/usr/bin/env bash
# Host test for the AMD SDK lifecycle hooks: the provision hook must hand stone
# each include path as one argument, never re-parsed by a shell, and both hooks
# must refuse a runtime name that would escape output/runtimes/.
# shellcheck disable=SC2015 # `check && ok || bad`: ok only echoes and counts, so bad runs only when the check failed
set -u
here=$(cd "$(dirname "$0")" && pwd)
prov=$here/../avocado-provision-amd-x86-64-v4
build=$here/../avocado-build-amd-x86-64-v4
w=$(mktemp -d); trap 'rm -rf "$w"' EXIT
pass=0; fail=0; ok(){ echo "  ok   - $1"; pass=$((pass+1)); }; bad(){ echo "  FAIL - $1"; fail=$((fail+1)); }

mkdir -p "$w/bin" "$w/prefix/runtimes/dev" "$w/sdk/stone"
truncate -s 5M "$w/prefix/runtimes/dev/avocado-image-var-amd-x86-64-v4.btrfs"
# stone stub: one argument per line, so an argument that got split or joined shows.
cat > "$w/bin/stone" <<S
#!/bin/bash
printf '%s\n' "\$@" > "$w/stone-args"
S
chmod +x "$w/bin/stone"

prov_run(){ rm -f "$w/stone-args" "$w/pwned"; (cd "$w" && PATH="$w/bin:$PATH" AVOCADO_PREFIX="$w/prefix" \
  AVOCADO_SDK_PREFIX="$w/sdk" AVOCADO_STONE_INCLUDE_PATHS="$1" bash "$prov" "$2") 2>&1; }

# 1. Plain paths reach stone as separate, exact arguments, in order.
out=$(prov_run "$w/inc one:$w/inc2" dev); rc=$?
want=$(printf '%s\n' provision -i "$w/sdk/stone" -i "$w/inc one" -i "$w/inc2" -i "$w/prefix/output/runtimes/dev/stone" --partition-size var=5242880)
{ [ $rc -eq 0 ] && [ "$(cat "$w/stone-args" 2>/dev/null)" = "$want" ]; } \
  && ok "include paths, spaces included, reach stone as exact arguments" || bad "args: rc=$rc out=[$out] got=[$(cat "$w/stone-args" 2>/dev/null)]"

# 2. Shell syntax in an include path is data, not code.
# shellcheck disable=SC2016 # the $(...) is the payload: it must stay literal
evil='x"; touch pwned; echo "$(touch pwned)'
out=$(prov_run "$evil" dev); rc=$?
{ [ ! -e "$w/pwned" ] && grep -qxF -- "$evil" "$w/stone-args" 2>/dev/null; } \
  && ok "shell syntax in an include path is passed through, never run" || bad "injection: rc=$rc pwned=$([ -e "$w/pwned" ] && echo yes || echo no) out=[$out]"

# 3/4. Both hooks refuse a missing or escaping runtime name.
for hook in prov build; do
  for name in "" "../escape" "a/b"; do
    if [ "$hook" = prov ]; then out=$(prov_run "" "$name"); rc=$?
    else out=$( (cd "$w" && AVOCADO_PREFIX="$w/prefix" AVOCADO_SDK_PREFIX="$w/sdk" bash "$build" "$name") 2>&1); rc=$?; fi
    [ $rc -ne 0 ] && echo "$out" | grep -qi "runtime name" && [ ! -e "$w/stone-args" ] && [ ! -d "$w/prefix/output/escape" ] \
      && ok "$hook hook refuses runtime name '$name'" || bad "$hook '$name': rc=$rc out=[$out]"
  done
done

echo
echo "passed: $pass  failed: $fail  (checks: $((pass + fail))/8 run)"
[ "$fail" -eq 0 ] && [ $((pass + fail)) -eq 8 ]
