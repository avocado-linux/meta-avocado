SUMMARY = "Avocado combination system/configuration extension"
DESCRIPTION = "Recipe for building Avocado extension packages"
LICENSE = "Apache-2.0"

# Extension parameters
EXT_ID ?= ""
EXT_VERSION ?= "${PV}"
EXT_DESCRIPTION ?= "Avocado extension"
EXT_PRIORITY ?= "50"

# EXT_TYPE: system, configuration, or combined
EXT_TYPE ?= "system"

# Set the runtime package name
PN = "avocado-extension-${@d.getVar('EXT_ID') or 'default'}"
PV = "1.0"

# Extension filename format
EXT_FILENAME = "${@d.getVar('EXT_ID') or 'unnamed'}"
EXT_FILENAME:append = "-${@d.getVar('EXT_VERSION')}"
EXT_FILENAME:append = ".${@d.getVar('EXT_TYPE')}"

# Extension dependencies - packages to include in the extension
EXT_DEPENDS ?= ""
RDEPENDS:${PN} = "systemd ${EXT_DEPENDS}"

# Define where extension files go
FILES:${PN} = "\
    /var/lib/extensions/${EXT_ID}/* \
    /var/lib/confexts/${EXT_ID}/* \
"

# Source directories for different extension types
EXT_SYSEXT_SRC_DIR ?= "${WORKDIR}/sysext-files"
EXT_CONFEXT_SRC_DIR ?= "${WORKDIR}/confext-files"

# Main installation task
do_install() {
    # Create metadata file
    cat > ${WORKDIR}/extension.conf << EOF
[Extension]
Type=${EXT_TYPE}
Priority=${EXT_PRIORITY}
Description=${EXT_DESCRIPTION}
Version=${EXT_VERSION}
EOF

    # Create release file
    cat > ${WORKDIR}/extension-release.${EXT_ID} << EOF
ID=${DISTRO}
VERSION_ID=${DISTRO_VERSION}
EOF

    # Process system extension files (for system or combined types)
    if [ "${EXT_TYPE}" = "system" ] || [ "${EXT_TYPE}" = "combined" ]; then
        install -d ${D}/var/lib/extensions/${EXT_ID}
        install -m 0644 ${WORKDIR}/extension.conf ${D}/var/lib/extensions/${EXT_ID}/
        
        install -d ${D}/var/lib/extensions/${EXT_ID}/usr/lib/extension-release.d
        install -m 0644 ${WORKDIR}/extension-release.${EXT_ID} ${D}/var/lib/extensions/${EXT_ID}/usr/lib/extension-release.d/
        
        if [ -d "${EXT_SYSEXT_SRC_DIR}" ]; then
            cp -R ${EXT_SYSEXT_SRC_DIR}/* ${D}/var/lib/extensions/${EXT_ID}/
        fi
    fi
    
    # Process configuration extension files (for configuration or combined types)
    if [ "${EXT_TYPE}" = "configuration" ] || [ "${EXT_TYPE}" = "combined" ]; then
        install -d ${D}/var/lib/confexts/${EXT_ID}
        install -m 0644 ${WORKDIR}/extension.conf ${D}/var/lib/confexts/${EXT_ID}/
        
        if [ -d "${EXT_CONFEXT_SRC_DIR}" ]; then
            cp -R ${EXT_CONFEXT_SRC_DIR}/* ${D}/var/lib/confexts/${EXT_ID}/
        fi
    fi

    # Check if we have any content
    has_content=0
    
    if [ -n "${EXT_DEPENDS}" ]; then
        has_content=1
    elif [ "${EXT_TYPE}" = "system" ] && [ -d "${EXT_SYSEXT_SRC_DIR}" ]; then
        has_content=1
    elif [ "${EXT_TYPE}" = "configuration" ] && [ -d "${EXT_CONFEXT_SRC_DIR}" ]; then
        has_content=1
    elif [ "${EXT_TYPE}" = "combined" ] && ([ -d "${EXT_SYSEXT_SRC_DIR}" ] || [ -d "${EXT_CONFEXT_SRC_DIR}" ]); then
        has_content=1
    fi
    
    # Fail on empty packages
    if [ "$has_content" = "0" ]; then
        bbfatal "Empty extension package: no content for extension type '${EXT_TYPE}'"
    fi
}

# No additional bundling - using only the RPM package

# Don't allow empty packages
ALLOW_EMPTY:${PN} = "0"
