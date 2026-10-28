# The QUP serial engines' firmware. I2C on these boards is built in
# (CONFIG_I2C_QCOM_GENI=y) and probes in the initramfs, and qcom-geni-se loads
# qupv3fw.elf itself, by the device tree's firmware-name. With the blob only in
# the BSP extension, merged later, every load fails, the I2C controllers stay
# in deferred probe for good (nothing binds afterwards to retry them), and on
# rb3gen2 the PCIe switch's I2C power control goes with them: no Ethernet, no
# USB 3. Both kernels (stock and PREEMPT_RT) behave the same.
RDEPENDS:${PN}:append:qcm6490 = " linux-firmware-qcom-qcm6490-qupv3fw"
