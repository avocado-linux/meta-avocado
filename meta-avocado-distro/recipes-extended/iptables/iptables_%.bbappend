# Backport: register --random-fully for DNAT in libxt_NAT.c.
#
# Upstream iptables (through 1.8.13 / current HEAD as of 2026-05-09) only
# registers --random-fully in SNAT_opts[] and MASQUERADE_opts[]. DNAT_opts[]
# is missing the option struct entry, even though the parse/print/save
# handlers (O_RANDOM_FULLY) already exist and are shared. The kernel xt_nat
# target supports the underlying NF_NAT_RANGE_PROTO_RANDOM_FULLY flag fine.
#
# k3s 1.28+ kube-proxy probes the kernel for RANDOM_FULLY support, sees it,
# then emits the flag on every ClusterIP DNAT rule. Without this patch
# every iptables-restore sync aborts at the first DNAT line and
# KUBE-SERVICES never populates, leaving every cluster-IP unreachable.
#
# We tried switching to the iptables-nft backend first; same userspace
# parser, same failure. The fix has to be at the parser layer.
FILESEXTRAPATHS:prepend := "${THISDIR}/${PN}:"

SRC_URI += "file://0001-extensions-NAT-register-random-fully-for-DNAT.patch"
