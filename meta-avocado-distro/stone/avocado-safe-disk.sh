# shellcheck shell=bash
#
# Wrong-disk protections for stone provisioning scripts that write a whole disk
# (sd and usb profiles). Sourced, never executed:
#
#   . "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/avocado-safe-disk.sh"
#
# Ships beside the script through the manifest's provision.files list, the same
# way build-disk-image.sh does, so it is resolved from the script's own
# directory in the stone data dir.
#
# fwup and dd both rewrite the partition table from sector 0, so a mistyped
# letter destroys whatever it names with no undo, and a development host
# routinely carries multi-terabyte disks on the same /dev/sd* namespace as the
# card reader. The checks mirror scripts/avocado-flash (assert_safe_block_device
# and confirm_destructive) so both ways of writing a card refuse the same
# targets.
#
# Every function prints its reason to stderr and returns 1; callers write
# `fn "$dev" || exit 1`. set -e is not relied on: it is suspended inside the
# conditionals these calls often sit in.
#
# Environment:
#   AVOCADO_PROVISION_FORCE     1 skips the retype (checks still run); 0 requires
#                               a terminal; see avocado_safe_disk_confirm
#   AVOCADO_PROVISION_DRY_RUN=1 run every guard, print each target-changing
#                               command instead of running it (1 only; 0 and
#                               anything else but unset or empty refuse)
#   AVOCADO_PROVISION_FWUP_TASK complete (default) or upgrade; validated here
#   AVOCADO_PROVISION_SYSBLOCK  sysfs block directory (default /sys/class/block)
#   AVOCADO_SAFE_DISK_MOUNTS    mount table (default /proc/self/mounts)
#   AVOCADO_SAFE_DISK_SWAPS     swap table (default /proc/swaps)
#   AVOCADO_SAFE_DISK_DEVDIR    where device nodes live (default /dev)
#   AVOCADO_PROVISION_HOST_MOUNTS  file holding the host's mount table, exported
#                               by avocado-cli; read as a second mount table
#   AVOCADO_SAFE_DISK_CONTAINER_MARKERS  files whose presence means "in a
#                               container" (default /.dockerenv /run/.containerenv)
#   AVOCADO_SAFE_DISK_EUID      effective uid avocado_safe_disk_run acts on
#                               (default: id -u); a test override
#
# Deliberately not used: lsblk and findmnt. The SDK images for several boards do
# not carry them, and a hard dependency would turn a working provision into a
# refusal. Mounts come from /proc/self/mounts, which is what lsblk reads, and
# the partition and root-disk relationships from sysfs.

# Set by avocado_safe_disk_check_device: the canonical node, with symlinks such
# as /dev/disk/by-id/... resolved, that every later check and the write use.
AVOCADO_SAFE_DISK_DEV=""
# Set by avocado_safe_disk_bus: what the bus decision was based on.
AVOCADO_SAFE_DISK_BUS=""

_asd_err() {
  echo "ERROR: $*" >&2
}

_asd_sysblock() {
  printf '%s' "${AVOCADO_PROVISION_SYSBLOCK:-/sys/class/block}"
}

_asd_is_block_node() {
  # stat rather than [ -b ]: same answer on a real node, and a PATH stub can
  # stand in for it where a test has no block device to point at.
  [ "$(stat -Lc %F -- "$1" 2>/dev/null)" = "block special file" ]
}

# The whole disk a block device name belongs to: itself, or for a partition the
# disk that holds it (sysfs nests a partition under its disk).
_asd_parent_disk() {
  local name=$1 sb real
  sb=$(_asd_sysblock)
  if [ -e "$sb/$name/partition" ]; then
    real=$(readlink -f -- "$sb/$name") || return 1
    basename -- "$(dirname -- "$real")"
  else
    printf '%s\n' "$name"
  fi
}

# Every block device name under the device mounted at /: the device itself, the
# disk beneath a partition, and whatever a dm/md/LVM volume is stacked on.
_asd_chain() {
  local name=$1 sb s
  sb=$(_asd_sysblock)
  printf '%s\n' "$name"
  if [ -e "$sb/$name/partition" ]; then
    _asd_chain "$(_asd_parent_disk "$name")" || return 1
  fi
  for s in "$sb/$name"/slaves/*; do
    [ -e "$s" ] || continue
    _asd_chain "$(basename -- "$s")" || return 1
  done
}

# Refuse anything that is not a block node the kernel knows as a whole disk.
# Sets AVOCADO_SAFE_DISK_DEV.
avocado_safe_disk_whole_disk() {
  local dev=$1 resolved name sb
  sb=$(_asd_sysblock)
  [ -n "$dev" ] || {
    _asd_err "no device specified"
    return 1
  }
  _asd_is_block_node "$dev" || {
    _asd_err "${dev} is not a block device"
    return 1
  }
  # /dev/disk/by-id and by-path entries are symlinks. Resolve before deriving
  # the sysfs name, or they pass the block test and then look like partitions.
  resolved=$(readlink -f -- "$dev") || {
    _asd_err "cannot resolve ${dev}"
    return 1
  }
  name=$(basename -- "$resolved")
  [ -e "$sb/$name" ] || {
    _asd_err "${dev} (${resolved}) is not a block device the kernel lists"
    return 1
  }
  if [ -e "$sb/$name/partition" ]; then
    _asd_err "${dev} is a partition; pass the whole disk (the image carries its own partition table)"
    return 1
  fi
  AVOCADO_SAFE_DISK_DEV=$resolved
}

# Require a USB or MMC bus, taken from udev's ID_PATH and not from the kernel's
# `removable` flag, which is wrong both ways: mmc_block never sets it, so a card
# in a native SDHCI reader reads 0, while the SCSI layer copies the device's RMB
# bit verbatim, so a USB enclosure asserting it passes. ID_PATH rather than
# ID_BUS, which is empty for nvme.
#
# A container usually has udevadm without the udev database, or neither. Then
# ID_PATH is empty and the decision uses the device's resolved sysfs path
# instead, which is the string udev derives ID_PATH from and holds `usb<N>` for
# a USB device and `mmc_host` for an MMC one. Only when neither can be read is
# the device refused.
avocado_safe_disk_bus() {
  local dev=${1:-$AVOCADO_SAFE_DISK_DEV} name sb id_path="" source="udev ID_PATH"
  sb=$(_asd_sysblock)
  name=$(basename -- "$(readlink -f -- "$dev")")
  AVOCADO_SAFE_DISK_BUS=""
  if command -v udevadm >/dev/null 2>&1; then
    id_path=$(udevadm info --query=property --property=ID_PATH --value "$dev" 2>/dev/null) \
      || id_path=""
  fi
  if [ -z "$id_path" ] && [ -e "$sb/$name" ]; then
    id_path=$(readlink -f -- "$sb/$name" 2>/dev/null) || id_path=""
    source="sysfs path"
  fi
  if [ -z "$id_path" ]; then
    _asd_err "refusing ${dev}: neither udev nor sysfs says which bus it is on"
    return 1
  fi
  case "$id_path" in
    *-usb-* | */usb[0-9]*/* | *mmc*) ;;
    *)
      _asd_err "refusing ${dev}: it is on '${id_path}' (${source}), not a USB or MMC bus; pass a card reader, SD slot or USB stick"
      return 1
      ;;
  esac
  AVOCADO_SAFE_DISK_BUS="${id_path} (${source})"
}

# Refuse a device that backs the running root filesystem, including through
# dm-crypt, LVM or md. A root on overlay, tmpfs or NFS has no local disk, which
# is the normal case inside the SDK container, so the guard is then vacuous
# rather than failing.
avocado_safe_disk_not_root() {
  local dev=${1:-$AVOCADO_SAFE_DISK_DEV} mounts src real name target chain
  mounts=${AVOCADO_SAFE_DISK_MOUNTS:-/proc/self/mounts}
  [ -r "$mounts" ] || {
    _asd_err "cannot read ${mounts}; refusing to guess what / is mounted from"
    return 1
  }
  src=$(awk '$2 == "/" { s = $1 } END { print s }' "$mounts")
  case "$src" in
    "${AVOCADO_SAFE_DISK_DEVDIR:-/dev}"/*) ;;
    *) return 0 ;;
  esac
  real=$(readlink -f -- "$src") || real=$src
  name=$(basename -- "$real")
  [ -e "$(_asd_sysblock)/$name" ] || {
    _asd_err "cannot tell which disk holds the running root (${src}); refusing to guess"
    return 1
  }
  target=$(basename -- "$(readlink -f -- "$dev")")
  chain=$(_asd_chain "$name") || {
    _asd_err "cannot trace the devices under /; refusing to guess"
    return 1
  }
  if printf '%s\n' "$chain" | grep -qxF -- "$target"; then
    _asd_err "${dev} holds the running root filesystem; refusing to overwrite"
    return 1
  fi
}

# Refuse a device, or any partition of it, that is mounted or in use as swap,
# including through a dm, LVM or md volume stacked on it. A filesystem still
# mounted while its disk is rewritten is corrupted. Inside the SDK container
# /proc/self/mounts shows only the container's namespace, so a host mount is
# invisible there; avocado-cli exports the host's table as the file named by
# AVOCADO_PROVISION_HOST_MOUNTS, read here as a second mount table. A named file
# that cannot be read refuses. In a container with it unset the check warns that
# host mounts were not checked and continues; on a host nothing is warned.
avocado_safe_disk_unmounted() {
  local dev=${1:-$AVOCADO_SAFE_DISK_DEV} target table src real name chain marker host=${AVOCADO_PROVISION_HOST_MOUNTS:-}
  local tables=("${AVOCADO_SAFE_DISK_MOUNTS:-/proc/self/mounts}" "${AVOCADO_SAFE_DISK_SWAPS:-/proc/swaps}")
  target=$(basename -- "$(readlink -f -- "$dev")")
  if [ -n "${AVOCADO_PROVISION_HOST_MOUNTS:-}" ]; then
    tables+=("$AVOCADO_PROVISION_HOST_MOUNTS")
  else
    for marker in ${AVOCADO_SAFE_DISK_CONTAINER_MARKERS:-/.dockerenv /run/.containerenv}; do
      if [ -e "$marker" ]; then
        # devtool-debt: a missing host mount table only warns. Ceiling: avocado-cli exporting no table. Upgrade trigger: the exporting avocado-cli release becomes the minimum; a missing table then refuses.
        echo "WARNING: running in a container and AVOCADO_PROVISION_HOST_MOUNTS is unset; host mounts of ${dev} were not checked" >&2
        break
      fi
    done
  fi
  for table in "${tables[@]}"; do
    [ -r "$table" ] || {
      _asd_err "refusing ${dev}: cannot read ${table}, so its mount state is unknown"
      return 1
    }
    # shellcheck disable=SC2094 # $table is only read; the dry-run note goes to stderr
    while read -r src _; do
      case "$src" in
        "${AVOCADO_SAFE_DISK_DEVDIR:-/dev}"/*) ;;
        *) continue ;;
      esac
      real=$(readlink -f -- "$src") || continue
      name=$(basename -- "$real")
      [ -e "$(_asd_sysblock)/$name" ] || continue
      chain=$(_asd_chain "$name") || {
        _asd_err "refusing ${dev}: cannot trace the devices under ${src}"
        return 1
      }
      if printf '%s\n' "$chain" | grep -qxF -- "$target"; then
        # A dry run does not unmount, so a mount in this namespace is reported
        # as one the real run would release; the host table is not ours to
        # release, so it refuses either way.
        if [ "${AVOCADO_PROVISION_DRY_RUN:-}" = "1" ] && [ "$table" != "$host" ]; then
          echo "dry run: ${src} is mounted or in use (${table##*/}); a real run would unmount it first" >&2
          continue
        fi
        _asd_err "refusing ${dev}: ${src} is mounted or in use (${table##*/}); unmount it first"
        return 1
      fi
    done <"$table"
  done
}

# Print what is about to be overwritten.
avocado_safe_disk_identity() {
  local dev=${1:-$AVOCADO_SAFE_DISK_DEV} name sb vendor model sectors size
  sb=$(_asd_sysblock)
  name=$(basename -- "$(readlink -f -- "$dev")")
  vendor="" model=""
  # [ -r ] first: a redirect from a missing file prints the shell's own open
  # error, which 2>/dev/null on the command does not cover.
  [ -r "$sb/$name/device/vendor" ] && vendor=$(tr -s ' ' <"$sb/$name/device/vendor" 2>/dev/null | xargs || true)
  [ -r "$sb/$name/device/model" ] && model=$(tr -s ' ' <"$sb/$name/device/model" 2>/dev/null | xargs || true)
  sectors=$(cat "$sb/$name/size" 2>/dev/null || echo 0)
  size=$(awk -v s="$sectors" 'BEGIN { printf "%.2f GiB", s * 512 / 1073741824 }')
  echo "Target device: ${dev}"
  echo "  Model: ${vendor:+$vendor }${model:-unknown}"
  echo "  Size:  ${size}"
  echo "  Bus:   ${AVOCADO_SAFE_DISK_BUS:-unchecked}"
}

# Whole disk, USB or MMC bus, and not the running root. The mount check is
# separate (avocado_safe_disk_unmounted) because the scripts unmount the target
# themselves and the check belongs after that.
avocado_safe_disk_check_device() {
  avocado_safe_disk_whole_disk "$1" || return 1
  avocado_safe_disk_bus "$AVOCADO_SAFE_DISK_DEV" || return 1
  avocado_safe_disk_not_root "$AVOCADO_SAFE_DISK_DEV" || return 1
}

# Show the target and apply the confirmation table. The table is pinned by
# tests/confirm-vectors.tsv, which the engine-side check reads too.
#
#   $1  device (printed form is the canonical node)
#   $2  ignored, kept so older callers that still pass it keep working; a device
#       named up front no longer skips the retype
#
# Retyping reads the terminal (stdin must be one) and accepts only exactly the
# target; a piped answer never confirms.
#
#   AVOCADO_PROVISION_DRY_RUN=1  asks no retype and never refuses on policy
#   AVOCADO_PROVISION_FORCE=1    skips the retype
#   AVOCADO_PROVISION_FORCE=0    retypes on a terminal, refuses without one
#   FORCE unset or empty         retypes on a terminal; without one proceeds
#   any other FORCE value        refuses before printing anything
avocado_safe_disk_confirm() {
  local dev=${1:-$AVOCADO_SAFE_DISK_DEV} reply="" force=${AVOCADO_PROVISION_FORCE:-}
  case "$force" in
    "" | 0 | 1) ;;
    *)
      _asd_err "AVOCADO_PROVISION_FORCE=${force} is not valid; use 1 or 0"
      return 1
      ;;
  esac
  echo ""
  avocado_safe_disk_identity "$dev"
  echo ""
  if [ "${AVOCADO_PROVISION_DRY_RUN:-}" = "1" ]; then
    echo "dry run: not asking for confirmation."
    return 0
  fi
  echo "WARNING: this overwrites everything on ${dev}."
  if [ "$force" = "1" ]; then
    echo "confirmation skipped: AVOCADO_PROVISION_FORCE=1"
    return 0
  fi
  if [ ! -t 0 ]; then
    if [ "$force" = "0" ]; then
      _asd_err "no terminal to confirm on; refusing to overwrite ${dev}"
      return 1
    fi
    # devtool-debt: callers that export no AVOCADO_PROVISION_FORCE proceed unconfirmed without a terminal. Ceiling: callers passing no force signal. Upgrade trigger: the avocado-cli release exporting the signal becomes the minimum; the row then refuses.
    echo "confirmation skipped: no terminal and no AVOCADO_PROVISION_FORCE signal"
    return 0
  fi
  printf 'Type the device path again to confirm: ' >&2
  IFS= read -r reply || reply=""
  if [ "$reply" != "$dev" ]; then
    _asd_err "confirmation did not match ${dev}; aborting"
    return 1
  fi
}

# Run one privileged tool: the only place these scripts escalate. As uid 0 the
# tool runs as is. Otherwise it is resolved to an absolute path here, as the
# invoking user, and run through sudo with that path: sudo resets PATH to its
# secure_path, which does not hold the SDK's fwup, and resets
# LD_LIBRARY_PATH, which the SDK's tools need, so the latter is forwarded
# explicitly through env. The guards never call this; they only read.
#
#   $1    tool name (resolved from PATH)
#   rest  its arguments
avocado_safe_disk_run() {
  local tool=${1:-} path
  [ -n "$tool" ] || {
    _asd_err "no tool given to run"
    return 1
  }
  shift
  path=$(command -v -- "$tool") && case "$path" in /*) ;; *) path="" ;; esac
  [ -n "$path" ] || {
    _asd_err "${tool} not found on PATH; cannot run it"
    return 1
  }
  if [ "${AVOCADO_SAFE_DISK_EUID:-$(id -u)}" = "0" ]; then
    "$path" "$@"
    return
  fi
  command -v sudo >/dev/null 2>&1 || {
    _asd_err "writing the disk with ${tool} needs root and sudo is not installed; rerun as root"
    return 1
  }
  if [ -n "${LD_LIBRARY_PATH:-}" ]; then
    sudo env "LD_LIBRARY_PATH=${LD_LIBRARY_PATH}" "$path" "$@"
  else
    sudo "$path" "$@"
  fi
}

# Run one command that changes the target (the image write, zeroing, unmount,
# swapoff). The only place a dry run is honoured: with
# AVOCADO_PROVISION_DRY_RUN=1 the command is printed and nothing runs. Callers
# validate the variable first (avocado_safe_disk_modes); any value but 1, empty
# or unset refuses here too, so an unvalidated value never runs or skips a write
# by accident.
#
#   rest  the command and its arguments; the tool is resolved as in _run
avocado_safe_disk_write() {
  if [ "${AVOCADO_PROVISION_DRY_RUN:-}" = "1" ]; then
    echo "dry-run: $*"
    return 0
  fi
  case "${AVOCADO_PROVISION_DRY_RUN:-}" in
    "") ;;
    *)
      _asd_err "AVOCADO_PROVISION_DRY_RUN=${AVOCADO_PROVISION_DRY_RUN} is not valid; refusing to write"
      return 1
      ;;
  esac
  avocado_safe_disk_run "$@"
}

# Validate the run-mode variables before any guard runs.
#
#   $1  profile name, used in refusals
#   $2  1 when the profile supports a dry run (its manifest declares it)
#   $3  1 when the profile can honour a task other than complete
avocado_safe_disk_modes() {
  local profile=${1:-?} dry_ok=${2:-0} task_ok=${3:-0}
  case "${AVOCADO_PROVISION_FORCE:-}" in
    "" | 0 | 1) ;;
    *)
      _asd_err "AVOCADO_PROVISION_FORCE=${AVOCADO_PROVISION_FORCE} is not valid; use 1 or 0"
      return 1
      ;;
  esac
  case "${AVOCADO_PROVISION_DRY_RUN:-}" in
    "") ;;
    1)
      [ "$dry_ok" = "1" ] || {
        _asd_err "profile ${profile} does not support a dry run"
        return 1
      }
      ;;
    *)
      _asd_err "AVOCADO_PROVISION_DRY_RUN=${AVOCADO_PROVISION_DRY_RUN} is not valid; use 1, or leave it unset"
      return 1
      ;;
  esac
  case "${AVOCADO_PROVISION_FWUP_TASK:-}" in
    "" | complete) ;;
    upgrade)
      [ "$task_ok" = "1" ] || {
        _asd_err "profile ${profile} cannot honour AVOCADO_PROVISION_FWUP_TASK=upgrade; only complete"
        return 1
      }
      ;;
    *)
      _asd_err "AVOCADO_PROVISION_FWUP_TASK=${AVOCADO_PROVISION_FWUP_TASK} is not valid; use complete or upgrade"
      return 1
      ;;
  esac
}

# Last line of a dry run. Silent otherwise.
#
#   $1  the target that was not written
avocado_safe_disk_finish() {
  [ "${AVOCADO_PROVISION_DRY_RUN:-}" = "1" ] || return 0
  echo "dry run: nothing was written to ${1:-$AVOCADO_SAFE_DISK_DEV}."
}

# Print the fwup task a writer should use. The only reader of
# AVOCADO_PROVISION_FWUP_TASK for fwup writers: complete by default, upgrade
# when asked, anything else refuses.
avocado_safe_disk_fwup_task() {
  case "${AVOCADO_PROVISION_FWUP_TASK:-}" in
    "" | complete) echo complete ;;
    upgrade) echo upgrade ;;
    *)
      _asd_err "AVOCADO_PROVISION_FWUP_TASK=${AVOCADO_PROVISION_FWUP_TASK} is not valid; use complete or upgrade"
      return 1
      ;;
  esac
}

# Print the SD target given up front: AVOCADO_PROVISION_DEVICE, with
# AVOCADO_SD_DEVICE as an alias. Prints nothing when neither is set; refuses
# when both are set to different values rather than picking one.
avocado_safe_disk_sd_device() {
  local a=${AVOCADO_PROVISION_DEVICE:-} b=${AVOCADO_SD_DEVICE:-}
  if [ -n "$a" ] && [ -n "$b" ] && [ "$a" != "$b" ]; then
    _asd_err "AVOCADO_PROVISION_DEVICE=${a} and AVOCADO_SD_DEVICE=${b} differ; set only one"
    return 1
  fi
  echo "${a:-$b}"
}

# Print the whole disks on a USB or MMC bus, one node per line, for a script
# choosing a lone target. The kernel removable flag is not consulted: it is
# wrong both ways (see avocado_safe_disk_bus). Nothing is printed for a host
# with no such disk; the caller decides what zero, one or many means.
avocado_safe_disk_bus_candidates() {
  local entry name node
  for entry in "$(_asd_sysblock)"/*; do
    [ -e "$entry" ] || continue
    name=$(basename -- "$entry")
    node="${AVOCADO_SAFE_DISK_DEVDIR:-/dev}/${name}"
    avocado_safe_disk_whole_disk "$node" 2>/dev/null || continue
    avocado_safe_disk_bus "$node" 2>/dev/null || continue
    echo "$node"
  done
}
