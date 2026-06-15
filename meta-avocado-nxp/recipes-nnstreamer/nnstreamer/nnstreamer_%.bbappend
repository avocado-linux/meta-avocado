# The i.MX8MP NPU inference path is tflite -> vx-delegate -> tim-vx -> OpenVX.
# NXP's nnstreamer turns on the TVM sub-plugin by default for mx8mp-nxp-bsp
# (PACKAGECONFIG_SOC = "tensorflow-lite tvm"), but TVM is a separate ML-compiler
# backend we don't use, and its tvm_runtime meson dependency doesn't resolve in
# this build (competing tvm_0.7.0 recipes in meta-imx-ml vs meta-ros, neither
# providing the expected target). Drop it -- the tflite2 / VX-delegate plugin
# the NPU reference uses is unaffected. (No-op on machines without tvm enabled.)
PACKAGECONFIG:remove = "tvm"
