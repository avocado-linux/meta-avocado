# linux-imx-headers ships under MACHINE_SOCARCH (cortexa55_mx93 for both
# imx93-frdm and imx93-evk) by default, but headers_install output differs
# per MACHINE within the same SoC tune — both boards produce distinct bytes
# despite identical NEVRA + arch. Two machines feeding the shared
# cortexa55_mx93 arch repo trigger Pulp's validate_duplicate_content (two
# content units, same NEVRA + arch, different sha256), failing the
# pulp-upload-distro task on add_and_remove. Forcing PACKAGE_ARCH to
# MACHINE_ARCH lands each machine's RPM in its own arch dir
# (avocado_imx93_frdm vs avocado_imx93_evk).
PACKAGE_ARCH = "${MACHINE_ARCH}"
