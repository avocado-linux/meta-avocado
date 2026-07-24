# NVIDIA container-runtime device passthrough fix for Thor (T264).
#
# tegra-configs ships devices.csv, the CSV the nvidia container runtime uses to
# bind-mount the integrated-GPU device nodes into containers. It hardcodes the
# Orin-era path /dev/nvgpu/igpu0/*, but the T264 (Thor) nvgpu driver exposes the
# GPU under a PCI-BDF path instead (/dev/nvgpu/igpu-0000:01:00.0/*). With the
# stale path the runtime can't find the GPU nodes on Thor, so `docker run
# --runtime nvidia` containers come up with no GPU and nvidia-smi reports
# "No devices found" (the host GPU is fine).
#
# Glob the igpu component so the csv matches BOTH the Orin (igpu0) and Thor
# (igpu-<pci-bdf>) device trees -- devices.csv already uses trailing globs
# elsewhere (e.g. /dev/dri/renderD*), and the runtime injects the matched nodes
# at their real host paths, which is where NVML/nvidia-smi look.
do_install:append() {
    csv="${D}${sysconfdir}/nvidia-container-runtime/host-files-for-container.d/devices.csv"
    if [ -f "${csv}" ]; then
        sed -i 's#/dev/nvgpu/igpu0/#/dev/nvgpu/igpu*/#g' "${csv}"
    fi
}
