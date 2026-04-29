SUMMARY = "NVIDIA GPU userspace compute libraries and tools"
DESCRIPTION = "Precompiled NVIDIA userspace binaries for GPU compute workloads. \
Includes nvidia-smi, libcuda, libnvidia-ml, CUDA MPS, nvidia-persistenced, \
and OpenCL support. For compute/headless use -- no display server integration."
HOMEPAGE = "https://www.nvidia.com/drivers/"

require nvidia-gpu-userspace.inc

SRC_URI += "file://nvidia-persistenced.service"

inherit systemd

SYSTEMD_SERVICE:${PN} = "nvidia-persistenced.service"
SYSTEMD_AUTO_ENABLE:${PN} = "enable"

# Runtime dependency on kernel modules and firmware
RDEPENDS:${PN} = " \
    nvidia-gpu-firmware \
"

do_configure[noexec] = "1"
do_compile[noexec] = "1"

do_install() {
    # ---- Libraries ----
    install -d ${D}${libdir}

    # Core compute libraries
    # libcuda -- CUDA driver API
    install -m 0755 ${S}/libcuda.so.${PV} ${D}${libdir}/
    ln -sf libcuda.so.${PV} ${D}${libdir}/libcuda.so.1
    ln -sf libcuda.so.1 ${D}${libdir}/libcuda.so

    # libnvidia-ml -- NVIDIA Management Library (nvidia-smi backend)
    install -m 0755 ${S}/libnvidia-ml.so.${PV} ${D}${libdir}/
    ln -sf libnvidia-ml.so.${PV} ${D}${libdir}/libnvidia-ml.so.1
    ln -sf libnvidia-ml.so.1 ${D}${libdir}/libnvidia-ml.so

    # libnvidia-ptxjitcompiler -- PTX JIT compiler
    install -m 0755 ${S}/libnvidia-ptxjitcompiler.so.${PV} ${D}${libdir}/
    ln -sf libnvidia-ptxjitcompiler.so.${PV} ${D}${libdir}/libnvidia-ptxjitcompiler.so.1
    ln -sf libnvidia-ptxjitcompiler.so.1 ${D}${libdir}/libnvidia-ptxjitcompiler.so

    # libnvidia-nvvm -- NVVM compiler library
    if [ -f ${S}/libnvidia-nvvm.so.${PV} ]; then
        install -m 0755 ${S}/libnvidia-nvvm.so.${PV} ${D}${libdir}/
        ln -sf libnvidia-nvvm.so.${PV} ${D}${libdir}/libnvidia-nvvm.so.1
        ln -sf libnvidia-nvvm.so.1 ${D}${libdir}/libnvidia-nvvm.so
    fi

    # libnvcuvid -- CUDA Video Decoder
    if [ -f ${S}/libnvcuvid.so.${PV} ]; then
        install -m 0755 ${S}/libnvcuvid.so.${PV} ${D}${libdir}/
        ln -sf libnvcuvid.so.${PV} ${D}${libdir}/libnvcuvid.so.1
        ln -sf libnvcuvid.so.1 ${D}${libdir}/libnvcuvid.so
    fi

    # libnvidia-encode -- NVIDIA Encoder
    if [ -f ${S}/libnvidia-encode.so.${PV} ]; then
        install -m 0755 ${S}/libnvidia-encode.so.${PV} ${D}${libdir}/
        ln -sf libnvidia-encode.so.${PV} ${D}${libdir}/libnvidia-encode.so.1
        ln -sf libnvidia-encode.so.1 ${D}${libdir}/libnvidia-encode.so
    fi

    # libnvidia-opencl -- NVIDIA OpenCL ICD
    if [ -f ${S}/libnvidia-opencl.so.${PV} ]; then
        install -m 0755 ${S}/libnvidia-opencl.so.${PV} ${D}${libdir}/
        ln -sf libnvidia-opencl.so.${PV} ${D}${libdir}/libnvidia-opencl.so.1
        ln -sf libnvidia-opencl.so.1 ${D}${libdir}/libnvidia-opencl.so
    fi

    # libnvidia-gpucomp -- GPU compute library
    if [ -f ${S}/libnvidia-gpucomp.so.${PV} ]; then
        install -m 0755 ${S}/libnvidia-gpucomp.so.${PV} ${D}${libdir}/
        ln -sf libnvidia-gpucomp.so.${PV} ${D}${libdir}/libnvidia-gpucomp.so
    fi

    # libnvidia-ngx -- NVIDIA NGX
    if [ -f ${S}/libnvidia-ngx.so.${PV} ]; then
        install -m 0755 ${S}/libnvidia-ngx.so.${PV} ${D}${libdir}/
        ln -sf libnvidia-ngx.so.${PV} ${D}${libdir}/libnvidia-ngx.so.1
        ln -sf libnvidia-ngx.so.1 ${D}${libdir}/libnvidia-ngx.so
    fi

    # libnvidia-allocator -- Memory allocator
    if [ -f ${S}/libnvidia-allocator.so.${PV} ]; then
        install -m 0755 ${S}/libnvidia-allocator.so.${PV} ${D}${libdir}/
        ln -sf libnvidia-allocator.so.${PV} ${D}${libdir}/libnvidia-allocator.so.1
        ln -sf libnvidia-allocator.so.1 ${D}${libdir}/libnvidia-allocator.so
    fi

    # libnvidia-cfg -- GPU configuration
    if [ -f ${S}/libnvidia-cfg.so.${PV} ]; then
        install -m 0755 ${S}/libnvidia-cfg.so.${PV} ${D}${libdir}/
        ln -sf libnvidia-cfg.so.${PV} ${D}${libdir}/libnvidia-cfg.so.1
        ln -sf libnvidia-cfg.so.1 ${D}${libdir}/libnvidia-cfg.so
    fi

    # ---- Binaries ----
    install -d ${D}${bindir}

    # nvidia-smi -- System Management Interface
    install -m 0755 ${S}/nvidia-smi ${D}${bindir}/

    # nvidia-modprobe -- setuid helper for loading modules and creating device nodes
    install -m 4755 ${S}/nvidia-modprobe ${D}${bindir}/

    # nvidia-persistenced -- persistence daemon
    install -m 0755 ${S}/nvidia-persistenced ${D}${bindir}/

    # CUDA MPS (Multi-Process Service)
    if [ -f ${S}/nvidia-cuda-mps-server ]; then
        install -m 0755 ${S}/nvidia-cuda-mps-server ${D}${bindir}/
    fi
    if [ -f ${S}/nvidia-cuda-mps-control ]; then
        install -m 0755 ${S}/nvidia-cuda-mps-control ${D}${bindir}/
    fi

    # ---- OpenCL ICD config ----
    install -d ${D}${sysconfdir}/OpenCL/vendors
    echo "libnvidia-opencl.so.1" > ${D}${sysconfdir}/OpenCL/vendors/nvidia.icd

    # ---- systemd service ----
    install -d ${D}${systemd_system_unitdir}
    install -m 0644 ${UNPACKDIR}/nvidia-persistenced.service \
        ${D}${systemd_system_unitdir}/nvidia-persistenced.service
}

# QA overrides for precompiled binaries
INSANE_SKIP:${PN} = "ldflags dev-so already-stripped libdir"

FILES:${PN} = " \
    ${libdir}/*.so* \
    ${bindir}/nvidia-smi \
    ${bindir}/nvidia-modprobe \
    ${bindir}/nvidia-persistenced \
    ${bindir}/nvidia-cuda-mps-server \
    ${bindir}/nvidia-cuda-mps-control \
    ${sysconfdir}/OpenCL \
    ${systemd_system_unitdir}/nvidia-persistenced.service \
"

# Skip dev/dbg packages -- these are precompiled
PACKAGES = "${PN}"
