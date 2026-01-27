FILESEXTRAPATHS:prepend := "${THISDIR}:"

SRC_URI += "file://0001-rust-fix-mismatched-lifetime-syntaxes-in-qr_code.patch"
SRC_URI += "file://0002-rust-add-v2-allocator-symbols-for-rust-1.89.patch"
