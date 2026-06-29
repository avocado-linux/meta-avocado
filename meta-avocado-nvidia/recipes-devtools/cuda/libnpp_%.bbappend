# See cuda-crt_%.bbappend for the explanation. Same fix.
CUDA_INSTALL_ARCH:class-nativesdk = "${@'sbsa' if d.getVar('HOST_ARCH') == 'aarch64' else d.getVar('HOST_ARCH')}"
