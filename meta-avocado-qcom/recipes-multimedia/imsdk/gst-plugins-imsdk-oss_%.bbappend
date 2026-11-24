# YOLOv8 dual-output post-processing (boxes + scores tensors) read box
# coordinates with the class-strided score index and labelled every detection
# class 0: wrong boxes for other classes and a SIGSEGV once a class >= 4 scored
# above threshold (reads past the 4 x anchors box tensor). Fixed upstream after
# 2.0.2; drop this when meta-qcom moves past it.
FILESEXTRAPATHS:prepend := "${THISDIR}/files:"
SRC_URI += "file://0001-mlpostprocess-yolov8-bug-fix.patch"
