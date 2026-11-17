#!/usr/bin/env bash
# Hands the provisioning run to the tegraflash engine. Stone runs this file in
# place from its data directory, which also holds the engine. Nothing here
# flashes: checks that the engine can start, then replaces this process with it.
set -eu

if [ -z "${AVOCADO_STONE_DATA_DIR:-}" ]; then
  echo "stone-provision-tegraflash: AVOCADO_STONE_DATA_DIR is unset or empty" >&2
  exit 1
fi
engine_dir="$AVOCADO_STONE_DATA_DIR/tegraflash-engine"
if [ ! -f "$engine_dir/avocado_tegraflash/__main__.py" ]; then
  echo "stone-provision-tegraflash: engine not found, looked in $engine_dir" >&2
  echo "the image tree predates the engine, or avocado-stone did not deploy it" >&2
  exit 1
fi
if ! command -v python3 >/dev/null 2>&1; then
  echo "stone-provision-tegraflash: python3 is needed and was not found on PATH" >&2
  exit 1
fi
if ! python3 -I -c 'import sys; sys.exit(sys.version_info < (3, 10))'; then
  found=$(python3 -I -c 'import sys; print("%d.%d" % sys.version_info[:2])')
  echo "stone-provision-tegraflash: python3 $found found, 3.10 needed" >&2
  exit 1
fi

# -I drops PYTHONPATH and the user site, -B keeps bytecode out of the data
# directory. The engine path travels as an argument, never inside the code.
# Appended, not prepended: a stray json.py in the data directory must not
# shadow the standard library when this runs as root.
exec python3 -I -B -c '
import runpy, sys
sys.path.append(sys.argv[1])
del sys.argv[1]
runpy.run_module("avocado_tegraflash", run_name="__main__", alter_sys=True)
' "$engine_dir" "$@"
