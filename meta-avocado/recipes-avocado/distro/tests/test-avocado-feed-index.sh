#!/usr/bin/env bash
# Host test for avocado_feed_index (classes/avocado-feed.bbclass), run against a
# fake deploy/rpm: the feed must be the avocado-repo.map layout made of relative
# symlinks (nothing copied), each repo must list exactly the RPMs deploy/rpm
# holds, and a re-index must drop what sstate removed while keeping extension
# RPMs dropped into target/<m>-ext. The function body is exec'd from the class
# itself with bb/d stubbed, so the test cannot drift from what bitbake runs.
# Needs python3, createrepo_c and rpmbuild.
set -u
here=$(cd "$(dirname "$0")" && pwd); class=$here/../../../classes/avocado-feed.bbclass
w=$(mktemp -d); trap 'rm -rf "$w"' EXIT
pass=0; fail=0; ok(){ echo "  ok   - $1"; pass=$((pass+1)); }; bad(){ echo "  FAIL - $1"; fail=$((fail+1)); }
for t in python3 createrepo_c rpmbuild; do command -v $t >/dev/null || { echo "skip: $t not found"; exit 0; }; done

rpm_dir=$w/deploy/rpm; feed=$w/deploy/avocado-feed
# One empty noarch RPM per name; the arch dir it lands in is what matters.
mkrpm(){ # name dir
    cat > "$w/$1.spec" <<EOF
Name: $1
Version: 1.0
Release: r0
Summary: t
License: MIT
BuildArch: noarch
%description
t
%files
EOF
    rpmbuild -bb --quiet --define "_topdir $w/rb" --define "_rpmdir $w/rb/out" "$w/$1.spec" >/dev/null 2>&1 &&
        mkdir -p "$rpm_dir/$2" && mv "$w"/rb/out/noarch/"$1"-*.rpm "$rpm_dir/$2/"
}
mkrpm tgt-a core2_64; mkrpm tgt-b core2_64; mkrpm tgt-m avocado_m1; mkrpm tgt-n noarch
mkrpm sdk-x x86_64_avocadosdk; mkrpm sdk-all all_avocadosdk
cat > "$rpm_dir/avocado-repo.map" <<'EOF'
aarch64_avocadosdk=$releasever/sdk/m1
all_avocadosdk=$releasever/sdk/all
avocado_m1=$releasever/target/m1/avocado_m1
core2_64=$releasever/target/m1/core2_64
noarch=$releasever/target/m1/noarch
x86_64_avocadosdk=$releasever/sdk/m1
repo=$releasever/sdk/all
repo=$releasever/sdk/m1
repo=$releasever/target/m1
EOF

index(){ python3 - "$class" "$rpm_dir" "$feed" <<'EOF'
import os, re, sys, types
body = re.search(r'python avocado_feed_index\(\) \{\n(.*?)\n\}', open(sys.argv[1]).read(), re.S).group(1)
v = {'DEPLOY_DIR_RPM': sys.argv[2], 'AVOCADO_FEED_DIR': sys.argv[3]}
bb = types.SimpleNamespace(
    build=types.SimpleNamespace(exec_func=lambda f, d: None),  # map is the fixture
    utils=types.SimpleNamespace(which=lambda p, n: '/usr/bin/createrepo_c',
                                mkdirhier=lambda p: os.makedirs(p, exist_ok=True)),
    fatal=lambda m: sys.exit(m), note=lambda m: None)
g = {'bb': bb}
exec("def f(d):\n" + body, g)
g['f'](types.SimpleNamespace(getVar=v.get))
EOF
}
count(){ zcat "$feed/$1"/repodata/*-primary.xml.gz 2>/dev/null | grep -o 'packages="[0-9]*"' | tr -dc 0-9; }

msg=$(index 2>&1); rc=$?
[ $rc -eq 0 ] && ok "index runs" || bad "index: rc=$rc $msg"

# Target arches nest under the machine root; flat sdk repos get the arch dir as a leaf.
for l in target/m1/core2_64:core2_64 target/m1/avocado_m1:avocado_m1 target/m1/noarch:noarch \
         sdk/m1/x86_64_avocadosdk:x86_64_avocadosdk sdk/all/all_avocadosdk:all_avocadosdk; do
    p=$feed/${l%%:*}; a=${l##*:}
    { [ -L "$p" ] && [ "$(readlink "$p")" = "$(python3 -c "import os,sys;print(os.path.relpath(sys.argv[1],sys.argv[2]))" "$rpm_dir/$a" "$(dirname "$p")")" ] && [ -d "$p/" ]; } &&
        ok "${l%%:*} is a relative link to rpm/$a" || bad "link ${l%%:*}: $(readlink "$p" 2>&1)"
done
# The map always names aarch64_avocadosdk; a build without it must not get a dangling link.
[ ! -e "$feed/sdk/m1/aarch64_avocadosdk" ] && [ ! -L "$feed/sdk/m1/aarch64_avocadosdk" ] &&
    ok "a mapped arch dir that was never built gets no link" || bad "dangling aarch64_avocadosdk link"
[ -z "$(find "$feed" -type f -name '*.rpm')" ] && ok "no RPM is copied into the feed" || bad "copied: $(find "$feed" -type f -name '*.rpm')"

[ "$(count target/m1)" = 4 ] && ok "target/m1 lists all 4 target RPMs across its arch dirs" || bad "target/m1 count $(count target/m1)"
[ "$(count sdk/m1)" = 1 ] && [ "$(count sdk/all)" = 1 ] && ok "sdk/m1 and sdk/all list their RPMs" || bad "sdk counts $(count sdk/m1)/$(count sdk/all)"
[ -f "$feed/target/m1-ext/repodata/repomd.xml" ] && [ "$(count target/m1-ext)" = 0 ] && ok "an empty target/m1-ext repo exists for extensions" || bad "ext repo: $(count target/m1-ext)"
zcat "$feed"/target/m1/repodata/*-primary.xml.gz | grep -q 'location href="core2_64/tgt-a-1.0-r0.noarch.rpm"' &&
    ok "hrefs resolve relative to the repo root through the link" || bad "href: $(zcat "$feed"/target/m1/repodata/*-primary.xml.gz | grep -o 'location href="[^"]*"' | head -2)"

before=$(find "$feed" -type l -printf '%p %l\n' | sort)
index >/dev/null 2>&1
[ "$(find "$feed" -type l -printf '%p %l\n' | sort)" = "$before" ] && ok "a re-index with no change leaves the links alone" || bad "links changed on no-op re-index"

# sstate removing an RPM, or a whole arch dir, must reach the feed on re-index,
# while an extension RPM packaged straight into target/m1-ext survives it.
cp "$rpm_dir/core2_64/tgt-b-1.0-r0.noarch.rpm" "$feed/target/m1-ext/ext-x-1.0-r0.noarch.rpm"
rm "$rpm_dir/core2_64/tgt-a-1.0-r0.noarch.rpm"; rm -rf "$rpm_dir/noarch"
msg=$(index 2>&1); rc=$?
[ $rc -eq 0 ] && [ "$(count target/m1)" = 2 ] && ok "removed RPMs and arch dirs leave target/m1 on re-index" || bad "after removal: rc=$rc count=$(count target/m1) $msg"
[ ! -L "$feed/target/m1/noarch" ] && ok "the link for a vanished arch dir is removed" || bad "stale noarch link kept"
[ "$(count target/m1-ext)" = 1 ] && ok "an extension RPM in target/m1-ext is indexed and kept" || bad "ext count $(count target/m1-ext)"

# A root the map stops naming (another machine built into this deploy dir) must
# stop serving metadata for links that are gone; its -ext repo keeps real RPMs.
sed -i 's,target/m1,target/m2,' "$rpm_dir/avocado-repo.map"
msg=$(index 2>&1); rc=$?
[ $rc -eq 0 ] && [ ! -e "$feed/target/m1/repodata" ] && [ "$(count target/m2)" = 2 ] &&
    ok "a root dropped from the map loses its repodata" || bad "dropped root: rc=$rc $(ls "$feed/target/m1" 2>&1) $msg"
[ "$(count target/m1-ext)" = 1 ] && ok "a dropped root's -ext repo and its RPM are kept" || bad "m1-ext count $(count target/m1-ext)"

# Pooled layout (AVOCADO_PERTARGET_REPOS=0): a package path that is also a repo
# root must not become the root itself, or createrepo_c writes into deploy/rpm.
rpm_dir=$w/pooled/rpm; feed=$w/pooled/avocado-feed
mkrpm pool-n noarch
cat > "$rpm_dir/avocado-repo.map" <<'MAP'
noarch=$releasever/target/noarch
repo=$releasever/target/noarch
MAP
msg=$(index 2>&1); rc=$?
[ $rc -eq 0 ] && [ -d "$feed/target/noarch" ] && [ ! -L "$feed/target/noarch" ] && [ -L "$feed/target/noarch/noarch" ] &&
    [ ! -e "$rpm_dir/noarch/repodata" ] && [ "$(count target/noarch)" = 1 ] &&
    ok "pooled: the root stays a directory and deploy/rpm gets no repodata" ||
    bad "pooled: rc=$rc root=$(ls -ld "$feed/target/noarch" 2>&1) rpm repodata=$(ls "$rpm_dir/noarch" 2>&1) $msg"

echo; echo "passed: $pass  failed: $fail"; [ $fail -eq 0 ]
