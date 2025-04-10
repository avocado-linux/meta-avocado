DESCRIPTION = "Avocado system and configuration extension image"
LICENSE = "Apache-2.0"

inherit image

# Configure image basics
IMAGE_FEATURES = ""
IMAGE_LINGUAS = ""

# Include requested packages
IMAGE_INSTALL = "${EXTENSION_PACKAGES}"

# Default value - override in extensions
EXTENSION_PACKAGES ?= ""

# Set the extension version and ID
EXT_ID ?= "debug-tweaks"
EXT_VERSION ?= "1"

# Extension installation directories
SYSEXT_DESTDIR = "/usr/lib/extensions"
CONFEXT_DESTDIR = "/usr/lib/confexts"

do_rootfs[vardeps] += "EXT_ID EXT_VERSION"

# Create the extension metadata and structure
ROOTFS_POSTPROCESS_COMMAND += "create_extension_metadata; "

create_extension_metadata() {
    # Create the extension metadata directory
    install -d ${IMAGE_ROOTFS}/usr/lib/extension-release.d/
    
    # Create the extension-release file with appropriate metadata
    cat > ${IMAGE_ROOTFS}/usr/lib/extension-release.d/extension-release.${EXT_ID} << EOF
ID=${DISTRO}
VERSION_ID=${DISTRO_VERSION}
SYSEXT_LEVEL=1
EXTENSION_ID=${EXT_ID}
EXTENSION_VERSION=${EXT_VERSION}
EXTENSION_COMBINED=1
EOF
    
    # Get the machine ID from the base system for compatibility if available
    if [ -f ${STAGING_DIR_TARGET}/usr/lib/os-release ]; then
        grep "^MACHINE_ID=" ${STAGING_DIR_TARGET}/usr/lib/os-release >> ${IMAGE_ROOTFS}/usr/lib/extension-release.d/extension-release.${EXT_ID} || true
    fi
}

# Build tar.bz2 for extension deployment
IMAGE_FSTYPES += "tar.bz2"

# Define our package and files
PACKAGES = "${PN}"
FILES:${PN} = "${SYSEXT_DESTDIR}/${EXT_ID}.raw ${CONFEXT_DESTDIR}/${EXT_ID}.raw"

# Package the extension image into an RPM
RPM_POSTINST_COMMANDS ?= "systemctl restart systemd-sysext; systemctl restart systemd-confext"
RPM_PRERM_COMMANDS ?= ""
RPM_POSTRM_COMMANDS ?= "systemctl restart systemd-sysext; systemctl restart systemd-confext"

# RPM package dependencies
RDEPENDS:${PN} += "systemd"

# Add RPM to image format types
IMAGE_TYPES += "rpm"

# Check if extension archive contains /etc files
def has_etc_files(archive_path):
    import tarfile
    
    # Check if the extension has etc files
    has_etc = False
    with tarfile.open(archive_path, 'r:bz2') as tar:
        for member in tar.getmembers():
            if member.name == 'etc' or member.name.startswith('etc/'):
                has_etc = True
                break
    
    return has_etc

# Prepare the extension package structure
def prepare_extension_package(d):
    import os
    import bb.utils
    import shutil
    
    # Get workspace directories
    workdir = d.getVar('WORKDIR')
    deploydir = d.getVar('DEPLOY_DIR_IMAGE')
    imgname = d.getVar('IMAGE_NAME')
    extid = d.getVar('EXT_ID')
    
    # Create package structure
    pkg_dir = os.path.join(workdir, 'extension-pkg-tree')
    bb.utils.remove(pkg_dir, True)
    bb.utils.mkdirhier(pkg_dir)
    
    # Create directory structure
    sysext_dir = os.path.join(pkg_dir, d.getVar('SYSEXT_DESTDIR').lstrip('/'))
    confext_dir = os.path.join(pkg_dir, d.getVar('CONFEXT_DESTDIR').lstrip('/'))
    bb.utils.mkdirhier(sysext_dir)
    bb.utils.mkdirhier(confext_dir)
    
    # Copy the extension image to the package structure
    src_ext = os.path.join(deploydir, imgname + '.rootfs.tar.bz2')
    dst_ext = os.path.join(sysext_dir, extid + '.raw')
    shutil.copy2(src_ext, dst_ext)
    
    # Check if the extension has etc files
    has_etc = has_etc_files(src_ext)
    
    # Create symlink for confext if needed
    if has_etc:
        os.symlink(
            os.path.join(d.getVar('SYSEXT_DESTDIR'), extid + '.raw'),
            os.path.join(confext_dir, extid + '.raw')
        )
    
    return (pkg_dir, src_ext)

# Create post-install and post-remove scripts
def create_post_scripts(workdir, postinst_cmds, postrm_cmds):
    import os
    import bb.utils
    
    # Create postinst script
    postinst_dir = os.path.join(workdir, 'extension-pkg-postinst')
    bb.utils.mkdirhier(postinst_dir)
    with open(os.path.join(postinst_dir, 'postinst'), 'w') as f:
        f.write('#!/bin/sh\n')
        f.write(postinst_cmds + '\n')
        f.write('exit 0\n')
    os.chmod(os.path.join(postinst_dir, 'postinst'), 0o755)
    
    # Create postrm script
    postrm_dir = os.path.join(workdir, 'extension-pkg-postrm')
    bb.utils.mkdirhier(postrm_dir)
    with open(os.path.join(postrm_dir, 'postrm'), 'w') as f:
        f.write('#!/bin/sh\n')
        f.write(postrm_cmds + '\n')
        f.write('exit 0\n')
    os.chmod(os.path.join(postrm_dir, 'postrm'), 0o755)

# Create RPM spec file for the extension
def create_rpm_spec_file(d, spec_dir, pkg_dir, src_ext):
    import os
    
    extid = d.getVar('EXT_ID')
    
    # Check if the extension has etc files
    has_etc = has_etc_files(src_ext)
    
    with open(os.path.join(spec_dir, 'extension.spec'), 'w') as f:
        pn = d.getVar('PN')
        version = d.getVar('EXT_VERSION')
        arch = d.getVar('TARGET_ARCH')
        
        f.write('Name: %s\n' % pn)
        f.write('Version: %s\n' % version)
        f.write('Release: 1\n')
        f.write('Summary: %s\n' % d.getVar('DESCRIPTION'))
        f.write('License: %s\n' % d.getVar('LICENSE'))
        f.write('BuildArch: %s\n' % arch)
        f.write('Requires: systemd\n')
        f.write('Provides: avocado-extension-%s\n' % extid)
        f.write('Provides: avocado-extension-%s-%s\n' % (extid, arch))
        
        f.write('\n%%description\n')
        f.write('%s\n' % d.getVar('DESCRIPTION'))
        f.write('Architecture-specific extension for %s.\n' % arch)
        
        f.write('\n%%prep\n')
        f.write('# Nothing to do\n')
        
        f.write('\n%%build\n')
        f.write('# Nothing to build\n')
        
        f.write('\n%%install\n')
        f.write('mkdir -p %{buildroot}\n')
        f.write('cp -R %s/* %{buildroot}/\n' % pkg_dir)
        
        f.write('\n%%files\n')
        f.write('%s/%s.raw\n' % (d.getVar('SYSEXT_DESTDIR'), extid))
        if has_etc:
            f.write('%s/%s.raw\n' % (d.getVar('CONFEXT_DESTDIR'), extid))
        
        f.write('\n%%post\n')
        f.write('%s\n' % d.getVar('RPM_POSTINST_COMMANDS'))
        
        f.write('\n%%postun\n')
        f.write('%s\n' % d.getVar('RPM_POSTRM_COMMANDS'))
    
    return os.path.join(spec_dir, 'extension.spec')

# Custom task to create the RPM package with our extension
fakeroot python do_bundle_extension() {
    import os
    import bb.utils
    import shutil
    
    # Prepare the extension package structure
    pkg_dir, src_ext = prepare_extension_package(d)
    workdir = d.getVar('WORKDIR')
    
    # Create post-install and post-remove scripts
    create_post_scripts(workdir, d.getVar('RPM_POSTINST_COMMANDS'), d.getVar('RPM_POSTRM_COMMANDS'))
    
    # Create RPM spec file
    spec_dir = os.path.join(workdir, 'extension-pkg-specs')
    bb.utils.mkdirhier(spec_dir)
    spec_file = create_rpm_spec_file(d, spec_dir, pkg_dir, src_ext)
    
    # Build the RPM
    bb.note("Building extension RPM package")
    rpmbuild_cmd = 'rpmbuild -bb --buildroot=%s --define "_topdir %s" %s' % (
        pkg_dir, workdir, spec_file)
    bb.process.run(rpmbuild_cmd)
    
    # Copy the built RPM to the deploy directory
    arch = d.getVar('TARGET_ARCH')
    pn = d.getVar('PN')
    version = d.getVar('EXT_VERSION')
    deploydir = d.getVar('DEPLOY_DIR_IMAGE')
    rpm_file = os.path.join(workdir, 'RPMS', arch, '%s-%s-1.%s.rpm' % (pn, version, arch))
    if os.path.exists(rpm_file):
        shutil.copy2(rpm_file, deploydir)
        bb.note("Extension RPM package created: %s" % rpm_file)
    else:
        bb.fatal("Failed to build extension RPM package")
}

addtask bundle_extension after do_image_complete before do_build
do_bundle_extension[depends] += "${PN}:do_image_complete"
