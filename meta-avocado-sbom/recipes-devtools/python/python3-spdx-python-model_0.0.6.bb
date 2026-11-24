SUMMARY = "Generated Python code for SPDX Spec version 3"
HOMEPAGE = "https://pypi.org/project/spdx-python-model/"
SECTION = "devel/python"
LICENSE = "Apache-2.0"
LIC_FILES_CHKSUM = "file://spdx_python_model-${PV}.dist-info/licenses/LICENSE;md5=86d3f3a95c324c9479bd8986968f4327"

# sbom-cve-check's one runtime dependency outside the standard library, which
# scarthgap OE-core does not have.
#
# The wheel, where OE-core builds the sdist. The sdist generates its bindings at
# build time with shacl2code, and its build backend asks for hatchling >= 1.27,
# hatch-build-scripts and shacl2code (which needs rdflib): scarthgap has
# hatchling 1.21.1 and none of the others. The wheel is pure Python and carries
# the generated bindings, so it is installed as it is, the way
# python_pep517_do_bootstrap_install installs one: unzipped into site-packages.
PYPI_PACKAGE = "spdx_python_model"
PYPI_SRC_URI = "https://files.pythonhosted.org/packages/py3/s/${PYPI_PACKAGE}/${PYPI_PACKAGE}-${PV}-py3-none-any.whl;downloadfilename=${PYPI_PACKAGE}-${PV}-py3-none-any.zip;subdir=${PYPI_PACKAGE}-${PV}"
SRC_URI[sha256sum] = "dd793ce0176e53af05f9c0d8624196f38da45bc263ccee5ee532b1812b3113e2"

inherit pypi python3native python3-dir setuptools3-base

do_configure[noexec] = "1"
do_compile[noexec] = "1"

do_install() {
    install -d ${D}${PYTHON_SITEPACKAGES_DIR}
    cp -R --no-preserve=ownership ${S}/spdx_python_model ${S}/spdx_python_model-${PV}.dist-info \
        ${D}${PYTHON_SITEPACKAGES_DIR}/
}

BBCLASSEXTEND = "native nativesdk"
