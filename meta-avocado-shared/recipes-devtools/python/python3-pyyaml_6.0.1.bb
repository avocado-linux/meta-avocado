SUMMARY = "Python support for YAML"
DEPENDS += "libyaml python3-cython-native"
HOMEPAGE = "https://pyyaml.org/"

LICENSE = "MIT"
LIC_FILES_CHKSUM = "file://LICENSE;md5=6d8242660a8371add5fe547adf083079"

PYPI_PACKAGE = "PyYAML"

inherit pypi python_setuptools_build_meta

SRC_URI += "file://0001-Fix-builds-with-Cython-3.patch"
SRC_URI[sha256sum] = "bfdf460b1736c775f2ba9f6a92bca30bc2095067b8a9d77876d1fad6cc3b4a43"

PACKAGECONFIG ?= "libyaml"
PACKAGECONFIG[libyaml] = "--with-libyaml,--without-libyaml,libyaml"

RDEPENDS:${PN} += "\
    python3-datetime \
    python3-netclient \
"

inherit ptest
# Work around BitBake unpack issue with test file in CI environments
# Remove the problematic test file from SRC_URI and handle it manually
SRC_URI += "\
    file://run-ptest \
"

# Store the test file info for manual handling
PYYAML_TEST_URL = "https://raw.githubusercontent.com/yaml/pyyaml/a98fd6088e81d7aca571220c966bbfe2ac43c335/tests/test_dump_load.py"
PYYAML_TEST_SHA256 = "b6a8a2825d89fdc8aee226560f66b8196e872012a0ea7118cbef1a832359434a"

# Manually handle the test file to work around CI unpack issues
python do_unpack:append() {
    workdir = d.getVar('WORKDIR')
    test_file = os.path.join(workdir, "test_dump_load.py")

    if not os.path.exists(test_file):
        dl_dir = d.getVar('DL_DIR')
        source_file = os.path.join(dl_dir, "test_dump_load.py")

        if os.path.exists(source_file):
            # Copy from downloads directory
            import shutil
            shutil.copy2(source_file, test_file)
        else:
            # Download directly if not in cache
            import urllib.request
            import hashlib

            test_url = d.getVar('PYYAML_TEST_URL')
            expected_sha256 = d.getVar('PYYAML_TEST_SHA256')

            urllib.request.urlretrieve(test_url, test_file)

            # Verify checksum
            with open(test_file, 'rb') as f:
                file_hash = hashlib.sha256(f.read()).hexdigest()

            if file_hash != expected_sha256:
                os.remove(test_file)
                bb.fatal("Downloaded test file checksum mismatch")
}

RDEPENDS:${PN}-ptest += " \
	python3-pytest \
	python3-unittest-automake-output \
"

do_install_ptest() {
	install -d ${D}${PTEST_PATH}/tests
	cp -rf ${WORKDIR}/test_dump_load.py ${D}${PTEST_PATH}/tests/
}

BBCLASSEXTEND = "native nativesdk"
