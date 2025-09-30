# CI Mirror Configuration

This directory contains KAS overlay configurations for CI builds that avoid locking issues when building in parallel on the same machine.

## Problem

When multiple CI jobs run in parallel on the same build machine, they compete for access to shared `DL_DIR` and `SSTATE_DIR` directories, causing locking conflicts and build failures.

## Solution

The `mirrors.yml` overlay configuration:

1. **Isolates builds**: Each build uses its own `DL_DIR` and `SSTATE_DIR` in `${TMPDIR}`
2. **Leverages shared cache**: Reads from shared mirror locations populated by regular builds
3. **Prevents conflicts**: No shared write access between parallel builds

## Usage

### In CI Workflows

Use the overlay syntax to apply CI configuration to any machine:

```bash
kas build machine.yml:ci/mirrors.yml --target TARGET
```

Example:
```bash
kas build distro/kas/machine/qemux86-64.yml:distro/kas/ci/mirrors.yml --target avocado-distro
```

### Environment Variables

Configure mirror locations via environment variables:

- `SOURCE_MIRROR_URL`: Location of shared download cache (default: `file:///avocado/dl`)
- `SSTATE_MIRRORS`: Location of shared sstate cache (default: `file:///avocado/sstate/PATH;downloadfilename=PATH`)
- `CI_MIRROR_ONLY`: Set to `1` to only use mirrors, no upstream fetching

### Local Development

Regular builds continue to use shared directories for priming:

```bash
# Regular build (uses shared DL_DIR and SSTATE_DIR)
kas build machine.yml --target TARGET

# CI-style build (uses mirrors)
kas build machine.yml:ci/mirrors.yml --target TARGET
```

## Cache Priming

To populate the shared cache for CI builds:

1. Run regular builds that write to `/avocado/dl` and `/avocado/sstate`
2. CI builds will read from these locations via mirrors
3. This provides the benefits of shared caching without locking conflicts

## Benefits

- ✅ No duplicate machine configurations to maintain
- ✅ Parallel CI builds don't conflict
- ✅ Shared cache benefits preserved
- ✅ Easy to toggle between local and CI modes
- ✅ Environment variable configuration





