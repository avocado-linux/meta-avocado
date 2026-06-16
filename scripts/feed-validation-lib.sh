#!/usr/bin/env bash
#
# feed-validation-lib.sh - shared steps for local feed validation.
#
# Sourced by validate-feed-local.sh (one case) and run-feed-validation.sh
# (the suite). Holds the reusable pipeline so cases differ only by package
# list: build -> stage -> render -> serve are shared fixtures; install +
# verify (+ optional boot) run per case.
#
# Build front-end is parameterized: AVOCADO_LOCAL_BUILD_CMD (default kas) is
# invoked as "<cmd> build <machine.yml>". A local build front-end that owns its
# own build directory and ccache can be swapped in via that env var; the build
# output is located under the build directory (default <workspace>/build-<machine>,
# overridable with AVOCADO_LOCAL_BUILD_DIR).
#
# Not executable on its own. set -euo pipefail is expected from the caller.

# --- resolve workspace layout from this file's location -------------------
FVL_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FVL_REPO_ROOT="$(cd "$FVL_SCRIPT_DIR/.." && pwd)" # meta-avocado
FVL_WORKSPACE="$(cd "$FVL_REPO_ROOT/.." && pwd)"  # kas workspace root

# --- tunables (env-overridable) -------------------------------------------
: "${AVOCADO_LOCAL_BUILD_CMD:=kas}"
: "${FVL_BUILD_TARGET:=avocado-complete}"
: "${AVOCADO_RELEASEVER:=2024/edge}"
: "${AVOCADO_REPO_URL:=http://localhost:8080}"

# --- counters / reporting -------------------------------------------------
FVL_PASS=0
FVL_FAIL=0
FVL_FAILED_CASES=()

fvl_log() { printf '\n=== %s ===\n' "$*"; }
fvl_info() { printf '    %s\n' "$*"; }
fvl_die() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

# Run one avocado step under a fresh pseudo-tty when stdin is not a terminal.
# avocado's container steps run `docker run -t`, which aborts with "cannot
# attach stdin to a TTY-enabled container" when there is no controlling
# terminal (CI, cron, a goal loop, a backgrounded run). A single shared pty for
# the whole runner is not enough: each interactive `docker` step (the build,
# then each install) consumes the pty's stdin and leaves the next step without
# a terminal. Allocating a fresh pty per command via `script` makes each step
# independent. An interactive terminal is passed through untouched.
fvl_pty() {
  if [ -t 0 ]; then
    "$@"
  else
    command -v script >/dev/null 2>&1 \
      || fvl_die "no tty and 'script' (util-linux) is not installed; avocado's docker -t steps need a pty"
    # </dev/null: script forwards its own stdin to the pty and would otherwise
    # drain the caller's stdin - e.g. the cases file the suite loops over via
    # `while read ... done <cases`, which would swallow every case after the
    # first. The avocado step needs the pty for docker -t, not stdin input.
    script -qe -c "$(printf '%q ' "$@")" /dev/null </dev/null
  fi
}

# fvl_case_pass <case> ; fvl_case_fail <case> <reason>
fvl_case_pass() {
  FVL_PASS=$((FVL_PASS + 1))
  printf 'PASS: %s\n' "$1"
}
fvl_case_fail() {
  FVL_FAIL=$((FVL_FAIL + 1))
  FVL_FAILED_CASES+=("$1")
  printf 'FAIL: %s - %s\n' "$1" "$2" >&2
}

# fvl_summary -> prints totals, returns non-zero if any case failed
fvl_summary() {
  fvl_log "Suite summary"
  printf '%d passed, %d failed\n' "$FVL_PASS" "$FVL_FAIL"
  if [ "$FVL_FAIL" -gt 0 ]; then
    printf 'Failed: %s\n' "${FVL_FAILED_CASES[*]}" >&2
    return 1
  fi
  return 0
}

# --- shared fixtures (run once per machine) -------------------------------

# fvl_build <machine> -> echoes the build's DEPLOY_DIR_RPM on stdout
# Runs "<AVOCADO_LOCAL_BUILD_CMD> build <machine.yml> --target <FVL_BUILD_TARGET>".
# FVL_BUILD_TARGET defaults to avocado-complete, which builds the distro AND one
# SDK (host arch by default) - the SDK packages (avocado-sdk-bootstrap, nativesdk)
# that `avocado sdk install` needs. avocado-distro alone does NOT produce them.
# For an aarch64 target on an x86_64 host, also set SDKMACHINE=aarch64.
# Note: kas honors --target; a builder that doesn't (e.g. one that only builds the
# kas yaml's target) needs FVL_BUILD_TARGET="" plus its own way to target
# avocado-complete. Then locates the build output under AVOCADO_LOCAL_BUILD_DIR,
# then <workspace>/build-<machine>[/build], then <workspace>/build[/build].
fvl_build() {
  local machine="$1"
  local kas_machine="$FVL_REPO_ROOT/kas/machine/${machine}.yml"
  [ -f "$kas_machine" ] || fvl_die "no kas machine config: $kas_machine"

  local target_args=()
  [ -n "$FVL_BUILD_TARGET" ] && target_args=(--target "$FVL_BUILD_TARGET")
  fvl_log "Produce: $AVOCADO_LOCAL_BUILD_CMD build $machine ${target_args[*]}" >&2
  (cd "$FVL_WORKSPACE" && $AVOCADO_LOCAL_BUILD_CMD build "$kas_machine" "${target_args[@]}") \
    || fvl_die "build failed for $machine"

  # The builder owns its build dir. kas defaults KAS_BUILD_DIR to <work>/build,
  # so a build-<machine> work dir yields build-<machine>/build; check both.
  local bdir deploy_rpm=""
  for bdir in "${AVOCADO_LOCAL_BUILD_DIR:-}" \
    "$FVL_WORKSPACE/build-${machine}/build" "$FVL_WORKSPACE/build-${machine}" \
    "$FVL_WORKSPACE/build/build" "$FVL_WORKSPACE/build"; do
    [ -n "$bdir" ] || continue
    if [ -f "$bdir/tmp/deploy/rpm/avocado-repo.map" ]; then
      deploy_rpm="$bdir/tmp/deploy/rpm"
      break
    fi
  done
  [ -n "$deploy_rpm" ] || fvl_die "no tmp/deploy/rpm with avocado-repo.map found (set AVOCADO_LOCAL_BUILD_DIR)"
  printf '%s\n' "$deploy_rpm"
}

# fvl_stage_and_render <deploy_rpm> <channel_root>
# Stages all RPMs, then renders EVERY repo root in avocado-repo.map (target/
# AND sdk/) into the content-addressed pool, so the local feed can serve the
# whole OS + toolchain + packages (not just one target repo).
fvl_stage_and_render() {
  local deploy_rpm="$1" channel_root="$2"
  # Keep the staged copy and createrepo temp on the same (large) filesystem as
  # the channel root, NOT on /tmp - a full deploy is several GB and /tmp is
  # often a size-capped tmpfs. The intermediate staged tree is removed after
  # rendering, since the pool retains the RPMs.
  local workbase
  workbase="$(dirname "$channel_root")"
  local staged="$workbase/staged"
  rm -rf "$staged"
  mkdir -p "$staged" "$channel_root"

  fvl_log "Stage RPMs -> $staged ($AVOCADO_RELEASEVER)" >&2
  bash "$FVL_REPO_ROOT/scripts/repo-stage-rpms.sh" \
    "$deploy_rpm" "$staged" "$AVOCADO_RELEASEVER" || fvl_die "staging failed"

  # Each "repo=<root>" line in the map is a repo to render. Roots carry a
  # literal "$releasever/" placeholder (repo-stage-rpms.sh eval-expands it at
  # stage time). Keep the releasever in the rendered subpath so the served repo
  # path matches what the consumer fetches: {repo}/{releasever}/target/<machine>.
  fvl_log "Render pool -> $channel_root (all repos)" >&2
  local rendered=0 line root sub
  while IFS= read -r line; do
    case "$line" in
      repo=*) root="${line#repo=}" ;;
      *) continue ;;
    esac
    sub="${root/\$releasever/$AVOCADO_RELEASEVER}" # e.g. dev/edge/target/qemux86-64
    [ -d "$staged/$sub" ] || continue
    fvl_info "render $sub" >&2
    TMPDIR="$workbase" python3 "$FVL_REPO_ROOT/scripts/render-pool-local.py" \
      --staged "$staged/$sub" \
      --channel-root "$channel_root" \
      --subpath "$sub" || fvl_die "render failed for $sub"
    rendered=$((rendered + 1))
  done <"$deploy_rpm/avocado-repo.map"
  rm -rf "$staged" # free the intermediate copy; the pool retains the RPMs
  [ "$rendered" -gt 0 ] || fvl_die "no repos rendered (empty avocado-repo.map?)"
  [ -d "$channel_root/_pkgs" ] || fvl_die "no _pkgs pool produced under $channel_root"
}

# fvl_serve <channel_root> <machine>
# Statically serves the rendered channel root over HTTP and waits for the
# target repo metadata to resolve. The render-pool output is already the
# production-served shape (repodata + _pkgs pool), so it just needs a plain
# static server - the support/sdk-test package-repo container is NOT used here:
# it mounts a raw <deploy>/rpm and runs its own flat createrepo, which does not
# serve a pre-rendered pool. The consumer reaches localhost from the SDK
# container via avocado's --network=host (Linux).
FVL_SERVE_PID=""
fvl_serve() {
  local channel_root="$1" machine="$2"
  local port="${AVOCADO_REPO_URL##*:}"
  case "$port" in '' | *[!0-9]*) port=8080 ;; esac
  # A prior run's sdk-test package-repo container may still hold the port; free
  # it best-effort so the static server can bind.
  docker compose -f "$FVL_REPO_ROOT/support/sdk-test/compose.yml" down >/dev/null 2>&1 || true
  local log
  log="$(mktemp)"
  fvl_log "Serve $channel_root at $AVOCADO_REPO_URL (static, port $port)" >&2
  python3 -m http.server "$port" --bind 0.0.0.0 --directory "$channel_root" >"$log" 2>&1 &
  FVL_SERVE_PID=$!
  local url="$AVOCADO_REPO_URL/$AVOCADO_RELEASEVER/target/$machine/repodata/repomd.xml"
  for _ in $(seq 1 30); do
    kill -0 "$FVL_SERVE_PID" 2>/dev/null || fvl_die "static server exited: $(cat "$log")"
    curl -fsS "$url" >/dev/null 2>&1 && return 0
    sleep 1
  done
  fvl_die "feed not reachable: $url (server log: $(cat "$log"))"
}

fvl_serve_down() {
  [ -n "${FVL_SERVE_PID:-}" ] && kill "$FVL_SERVE_PID" >/dev/null 2>&1 || true
  docker compose -f "$FVL_REPO_ROOT/support/sdk-test/compose.yml" down >/dev/null 2>&1 || true
}

# --- per-case steps -------------------------------------------------------

# Per-case work runs inside a scaffolded avocado project. `avocado init` creates
# a project with a default `app` extension and `--network=host` in the SDK
# container_args (so the SDK container reaches the host feed at localhost), which
# is exactly what the consume step needs. Packages install into the `app` ext;
# per-case isolation comes from a fresh project dir per case.
FVL_EXT="app"

# fvl_scaffold_project <machine> <projdir>
fvl_scaffold_project() {
  local machine="$1" projdir="$2"
  rm -rf "$projdir"
  mkdir -p "$projdir"
  avocado init --target "$machine" --no-tui "$projdir" >/dev/null 2>&1 \
    || fvl_die "avocado init failed for $projdir"
  # The default 'dev' runtime references avocado-ext-dev / -sshd-dev / -bsp,
  # which a local distro+SDK feed does not contain (they live in the separate
  # -ext extension feed). Drop them from the runtime list so rootfs install does
  # not try to fetch them; the package install only needs the local 'app' (and
  # 'config') extensions.
  sed -i -E '/^[[:space:]]+- avocado-(ext-|bsp-)/d' "$projdir/avocado.yaml"
}

# fvl_install_case <machine> <projdir> <packages...>
# Bootstrap order matters: `avocado sdk install` installs the SDK sysroot, which
# provides the target dnf repo config (target-repoconf) that DNF_SDK_TARGET_REPO_CONF
# points at - without it the target repoquery sees no repos. `avocado rootfs
# install` then installs the rootfs sysroot, whose rpmdb `avocado ext dnf` copies
# to seed the extension. Only then does the package install into the app ext.
fvl_install_case() {
  local machine="$1" projdir="$2"
  shift 2
  (
    cd "$projdir" || exit 1
    export AVOCADO_REPO_URL AVOCADO_RELEASEVER
    # -f bypasses avocado's interactive confirmation; -y answers the dnf
    # transaction prompt. Both are required for non-interactive runs: under a
    # pty (needed for the docker -t install steps) dnf would otherwise block
    # on "Is this ok [y/N]:" forever.
    fvl_pty avocado sdk install -f || exit 1
    fvl_pty avocado rootfs install -f || exit 1
    fvl_pty avocado ext dnf -e "$FVL_EXT" --target "$machine" install -y "$@"
  )
}

# fvl_verify_sdk_case <machine> <projdir> <pkg_csv> <lib_csv>
# Asserts each package is installed in the app ext rpmdb, and each expected lib
# (if any) is present in the ext sysroot. Returns non-zero on first miss.
fvl_verify_sdk_case() {
  local machine="$1" projdir="$2" pkg_csv="$3" lib_csv="$4"
  (
    cd "$projdir" || exit 1
    export AVOCADO_REPO_URL AVOCADO_RELEASEVER
    local pkg lib out
    for pkg in ${pkg_csv//,/ }; do
      # avocado runs the dnf container with docker -t, so the result line
      # lands on stdout or stderr depending on tty detection. Capture both with
      # 2>&1 into a variable (not `2>/dev/null | grep -q .`, which drops the
      # result when it goes to stderr and false-positives on the [INFO] line
      # when it goes to stdout). Match the package token from repoquery output.
      out=$(fvl_pty avocado ext dnf -e "$FVL_EXT" --target "$machine" -- \
        repoquery --installed "$pkg" 2>&1 || true)
      printf '%s\n' "$out" | tr -d '\r' | grep -Eq "(^|[^[:alnum:]_])${pkg}-[0-9]" \
        || {
          printf '%s not installed in ext %s\n' "$pkg" "$FVL_EXT" >&2
          exit 1
        }
    done
    for lib in ${lib_csv//,/ }; do
      [ -n "$lib" ] || continue
      fvl_pty avocado sdk run --target "$machine" -- \
        sh -c "ls \"\$AVOCADO_EXT_SYSROOTS/$FVL_EXT\"/usr/lib*/$lib* >/dev/null 2>&1" \
        || {
          printf '%s missing in ext %s sysroot\n' "$lib" "$FVL_EXT" >&2
          exit 1
        }
    done
  )
}

# --- boot tier (e2e on a booted qemux86-64) -------------------------------
#
# Verifies an extension merged on a booted target without ssh: the local
# distro+SDK feed has no sshd extension, so assertions go over the QEMU guest
# agent. qemu-guest-agent ships in the rootfs (kas/feature/qemu-guest-agent.yml)
# and `vm --qga-port` exposes the org.qemu.guest_agent.0 channel as a host TCP
# socket (reachable via --network=host). Heavy: one full image build + boot per
# boot-marked case. Tune via FVL_QGA_PORT / FVL_BOOT_WAIT.

FVL_QGA_PORT="${FVL_QGA_PORT:-4445}"
# Max wait for the guest agent (the wait returns as soon as the agent answers,
# so a higher value never slows a fast boot). Default headroom covers a
# cross-arch TCG boot: on an x86_64 host qemu-system-aarch64 has no KVM, so an
# emulated qemuarm64 boot to userspace is minutes, not seconds.
FVL_BOOT_WAIT="${FVL_BOOT_WAIT:-600}"

# fvl_qga <args...> -> host-side QGA client against FVL_QGA_PORT
fvl_qga() {
  python3 "$FVL_REPO_ROOT/scripts/qga-exec.py" --port "$FVL_QGA_PORT" "$@"
}

# fvl_assert_in_target <ext> <lib_csv>
# Asserts the extension is merged and each expected lib is present on the
# running target's merged /usr, via guest-exec. Generic: no per-package binary.
fvl_assert_in_target() {
  local ext="$1" lib_csv="$2" lib
  fvl_qga --run "avocadoctl status" 2>/dev/null | grep -qi "$ext" \
    || {
      printf 'ext %s not merged on target\n' "$ext" >&2
      return 1
    }
  for lib in ${lib_csv//,/ }; do
    [ -n "$lib" ] || continue
    fvl_qga --run "ls /usr/lib*/$lib* >/dev/null 2>&1" \
      || {
        printf '%s missing on target /usr\n' "$lib" >&2
        return 1
      }
  done
  return 0
}

# fvl_boot_verify_case <machine> <projdir> <pkg_csv> <lib_csv>
# One full image cycle: scaffold project -> install packages into the app ext ->
# build -> provision -> boot -> assert -> reboot -> re-assert. Returns 0/1.
fvl_boot_verify_case() {
  local machine="$1" projdir="$2" pkg_csv="$3" lib_csv="$4"
  local cname="fv-vm-${machine}-$$"
  fvl_scaffold_project "$machine" "$projdir"
  # shellcheck disable=SC2086  # intentional: split the csv into separate args
  fvl_install_case "$machine" "$projdir" ${pkg_csv//,/ } \
    || {
      printf 'boot: package install failed\n' >&2
      return 1
    }
  (
    cd "$projdir" || exit 1
    export AVOCADO_REPO_URL AVOCADO_RELEASEVER
    fvl_pty avocado install -f >/dev/null 2>&1 || exit 1
    fvl_pty avocado build >/dev/null 2>&1 || exit 1
    fvl_pty avocado provision -r dev >/dev/null 2>&1 || exit 1
  ) || {
    printf 'boot: build/provision failed\n' >&2
    return 1
  }

  # Launch the VM detached with the guest-agent channel. -d returns once the
  # container is up (an interactive -i run would need a tty on stdin, which a
  # backgrounded launch lacks). qemu runs inside it; the host reaches the agent
  # on 127.0.0.1:$FVL_QGA_PORT.
  (cd "$projdir" && avocado sdk run -d --name "$cname" -E vm dev --qga-port "$FVL_QGA_PORT") >/dev/null \
    || {
      printf 'boot: vm launch failed\n' >&2
      return 1
    }

  local rc=0
  if ! fvl_qga --wait --deadline "$FVL_BOOT_WAIT"; then
    rc=1
    printf 'boot: guest agent never came up\n' >&2
  fi
  if [ "$rc" -eq 0 ] && ! fvl_assert_in_target "$FVL_EXT" "$lib_csv"; then rc=1; fi
  if [ "$rc" -eq 0 ]; then
    fvl_qga --run "reboot" >/dev/null 2>&1 || true
    sleep 5
    if ! fvl_qga --wait --deadline "$FVL_BOOT_WAIT"; then
      rc=1
      printf 'boot: guest did not return after reboot\n' >&2
    elif ! fvl_assert_in_target "$FVL_EXT" "$lib_csv"; then
      rc=1
      printf 'boot: ext/libs gone after reboot\n' >&2
    fi
  fi

  fvl_qga --run "poweroff" >/dev/null 2>&1 || true
  sleep 3
  docker rm -f "$cname" >/dev/null 2>&1 || true
  return "$rc"
}
