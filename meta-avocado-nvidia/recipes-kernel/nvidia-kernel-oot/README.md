# nvidia-kernel-oot Development Source Packages

This directory contains a bbappend that creates `-devsrc` packages for nvidia-kernel-oot, enabling users to build out-of-tree kernel modules that depend on NVIDIA kernel module headers and symbols.

## Overview

The `nvidia-kernel-oot` recipe builds out-of-tree kernel modules for NVIDIA Jetson platforms when using an upstream kernel. When users want to compile their own kernel modules that depend on NVIDIA-specific headers or symbols (e.g., nvgpu, nvmap, camera subsystems), they need access to:

1. **Module.symvers** - Contains exported symbols from nvidia-kernel-oot modules
2. **Header files** - NVIDIA-specific kernel headers
3. **kernel-devsrc** - The base kernel development sources

The `-devsrc` packages provide these files in a structure similar to `kernel-devsrc`.

## Available Packages

| Package | Description |
|---------|-------------|
| `nvidia-kernel-oot-devsrc` | Main package with all development sources |
| `nvidia-kernel-oot-display-devsrc` | Convenience package for display subsystem |
| `nvidia-kernel-oot-cameras-devsrc` | Convenience package for camera subsystem |
| `nvidia-kernel-oot-base-devsrc` | Convenience package for base subsystem |

The category-specific packages are empty but depend on the main `-devsrc` package, allowing for future granular splitting if needed.

## Installation Path

The devsrc package installs files to:

```
/usr/src/nvidia-oot/
├── Module.symvers           # Exported symbols from nvidia-kernel-oot
├── .nvidia-kernel-oot-version  # Version for compatibility checking
├── include/                 # Header files
├── nvidia-oot/              # nvidia-oot source tree (headers, Makefiles, Kconfig)
├── nvdisplay/               # Display subsystem headers
├── kernel-devicetree/       # Device tree sources (.dts, .dtsi, .h)
└── Makefile                 # Top-level Makefile
```

## Usage in Avocado Extensions

### 1. Add Package Dependencies

In your extension's `avocado.yaml`, add the required SDK packages:

```yaml
extensions:
  my-nvidia-kmod:
    # ... other config ...
    
    sdk:
      packages:
        kernel-devsrc: '*'
        # nvidia-kernel-oot-devsrc is included automatically for tegra targets
        # via packagegroup-avocado-tegra-sdk-extra

sdk:
  compile:
    my-module-build:
      compile: build-module.sh
      packages:
        kernel-devsrc: '*'
```

### 2. Build Script Example

Create a compile script that uses `KBUILD_EXTRA_SYMBOLS` to resolve NVIDIA symbols:

```bash
#!/usr/bin/env bash
set -e

echo "Building kernel module with NVIDIA dependencies"

# Find kernel version
KERNEL_VERSION=$(cat "${OECORE_TARGET_SYSROOT}/usr/src/kernel/include/config/kernel.release")
KDIR="${OECORE_TARGET_SYSROOT}/usr/src/kernel"

# Point to nvidia-kernel-oot Module.symvers for symbol resolution
NVIDIA_SYMVERS="${OECORE_TARGET_SYSROOT}/usr/src/nvidia-oot/Module.symvers"

if [ ! -f "$NVIDIA_SYMVERS" ]; then
    echo "ERROR: nvidia-kernel-oot-devsrc not installed"
    echo "Make sure nvidia-kernel-oot-devsrc is in your SDK packages"
    exit 1
fi

# Optional: Add nvidia headers to include path
NVIDIA_INCLUDES="${OECORE_TARGET_SYSROOT}/usr/src/nvidia-oot/include"

# Run modules_prepare if needed (same as v4l2loopback example)
if [ ! -x "$KDIR/scripts/mod/modpost" ]; then
    echo "Running modules_prepare..."
    make -C ${KDIR} \
        ARCH=${ARCH} \
        CROSS_COMPILE=${CROSS_COMPILE} \
        modules_prepare
fi

# Build the module with NVIDIA symbol support
make -C ${KDIR} \
    M=$(pwd) \
    ARCH=${ARCH} \
    CROSS_COMPILE=${CROSS_COMPILE} \
    KBUILD_EXTRA_SYMBOLS=${NVIDIA_SYMVERS} \
    EXTRA_CFLAGS="-I${NVIDIA_INCLUDES}" \
    modules

echo "Build complete!"
```

### 3. Module Makefile Example

Your kernel module's Makefile should include NVIDIA headers if needed:

```makefile
obj-m := my_nvidia_module.o

# Include NVIDIA headers (set via EXTRA_CFLAGS in build script)
# ccflags-y += -I$(NVIDIA_INCLUDES)

my_nvidia_module-objs := main.o nvidia_helpers.o
```

## Common Use Cases

### Camera Module Development

For modules that interact with NVIDIA camera subsystems:

```bash
NVIDIA_SYMVERS="${OECORE_TARGET_SYSROOT}/usr/src/nvidia-oot/Module.symvers"
NVIDIA_CAM_INCLUDES="${OECORE_TARGET_SYSROOT}/usr/src/nvidia-oot/nvidia-oot/drivers/media"

make -C ${KDIR} M=$(pwd) \
    KBUILD_EXTRA_SYMBOLS=${NVIDIA_SYMVERS} \
    EXTRA_CFLAGS="-I${NVIDIA_CAM_INCLUDES}" \
    modules
```

### GPU/Display Module Development

For modules that interact with nvgpu or display subsystems:

```bash
NVIDIA_SYMVERS="${OECORE_TARGET_SYSROOT}/usr/src/nvidia-oot/Module.symvers"
NVIDIA_GPU_INCLUDES="${OECORE_TARGET_SYSROOT}/usr/src/nvidia-oot/nvidia-oot/drivers/gpu/nvgpu/include"
NVDISPLAY_INCLUDES="${OECORE_TARGET_SYSROOT}/usr/src/nvidia-oot/nvdisplay"

make -C ${KDIR} M=$(pwd) \
    KBUILD_EXTRA_SYMBOLS=${NVIDIA_SYMVERS} \
    EXTRA_CFLAGS="-I${NVIDIA_GPU_INCLUDES} -I${NVDISPLAY_INCLUDES}" \
    modules
```

### Multiple Extra Symbol Files

If your module depends on multiple out-of-tree modules:

```bash
# Combine multiple Module.symvers files
KBUILD_EXTRA_SYMBOLS="${NVIDIA_SYMVERS} ${OTHER_MODULE_SYMVERS}"

make -C ${KDIR} M=$(pwd) \
    KBUILD_EXTRA_SYMBOLS="${KBUILD_EXTRA_SYMBOLS}" \
    modules
```

## Version Compatibility

The devsrc package includes a version file at:
```
/usr/src/nvidia-oot/.nvidia-kernel-oot-version
```

You can check this in your build scripts to ensure compatibility:

```bash
NVIDIA_OOT_VERSION=$(cat "${OECORE_TARGET_SYSROOT}/usr/src/nvidia-oot/.nvidia-kernel-oot-version")
echo "Building against nvidia-kernel-oot version: $NVIDIA_OOT_VERSION"
```

## Troubleshooting

### "Unknown symbol" errors during module load

This usually means the module was built without proper symbol resolution. Ensure:
1. `KBUILD_EXTRA_SYMBOLS` points to the correct `Module.symvers`
2. The nvidia-kernel-oot modules are loaded before your module
3. Your module's `modprobe` list includes nvidia dependencies

### Missing header files

Check that `nvidia-kernel-oot-devsrc` is installed:
```bash
ls ${OECORE_TARGET_SYSROOT}/usr/src/nvidia-oot/
```

### Symbol version mismatch

Ensure your SDK's nvidia-kernel-oot-devsrc matches the target's nvidia-kernel-oot version. The version file can help verify this.

## See Also

- `kmod-v4l2loopback` extension for a working out-of-tree module example
- `kernel-devsrc.bbappend` in meta-avocado-distro for kernel devsrc customizations
