FILESEXTRAPATHS:prepend := "${@':'.join(['%s/stone' % layer for layer in d.getVar('BBLAYERS').split()])}:"
FILESEXTRAPATHS:prepend := "${@':'.join(['%s/stone/${MACHINE_SHORT_NAME}' % layer for layer in d.getVar('BBLAYERS').split()])}:"
