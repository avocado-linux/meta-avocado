FILESEXTRAPATHS:prepend:arm64-uefi := "${THISDIR}/files:"

SRC_URI:append:arm64-uefi = " file://avocado-boot.conf file://avocado-loader.conf"

# Write the boot entry $1 to $3 with one console=<tty>,<baud>n8 per
# SERIAL_CONSOLES entry ($2) appended to its options line. A device-tree
# platform gets no console from an ACPI SPCR table, so without this its kernel
# goes silent once the early console is disabled. An empty list copies the
# entry unchanged. POSIX only, and no braced expansions in here: BitBake would
# expand them at parse time. Inputs are arguments so the host test can run it.
avocado_arm64_boot_entry() {
    abe_src=$1
    abe_args=
    # Word splitting on whitespace is the SERIAL_CONSOLES list syntax.
    # shellcheck disable=SC2086
    for abe_entry in $2; do
        abe_baud=$(printf '%s\n' "$abe_entry" | cut -d ';' -f 1)
        abe_tty=$(printf '%s\n' "$abe_entry" | cut -d ';' -f 2)
        case $abe_entry in
            *';'*) ;;
            *) abe_tty= ;;
        esac
        # A swapped entry such as ttyAMA0;115200 has fields, but would put a
        # tty name where the baud goes and leave the console silent.
        case $abe_baud in
            *[!0-9]*) abe_baud= ;;
        esac
        case $abe_tty in
            */*) abe_tty= ;;
        esac
        if [ -z "$abe_baud" ] || [ -z "$abe_tty" ]; then
            echo "avocado_arm64_boot_entry: malformed SERIAL_CONSOLES entry '$abe_entry', expected <baud>;<tty> with a numeric baud and a tty name without a slash" >&2
            return 1
        fi
        abe_args="$abe_args console=$abe_tty,$abe_baud""n8"
    done
    if [ -z "$abe_args" ]; then
        cp "$abe_src" "$3"
        return 0
    fi
    while true; do
        if IFS= read -r abe_line; then
            abe_end=1
        elif [ -n "$abe_line" ]; then
            abe_end=
        else
            break
        fi
        case $abe_line in
            'options '*) abe_line="$abe_line$abe_args" ;;
        esac
        if [ -n "$abe_end" ]; then
            printf '%s\n' "$abe_line"
        else
            printf '%s' "$abe_line"
            break
        fi
    done < "$abe_src" > "$3"
}

do_install:arm64-uefi() {
    install -d ${D}/boot/loader/entries
    install -m 0644 ${S}/avocado-loader.conf ${D}/boot/loader/loader.conf
    avocado_arm64_boot_entry ${S}/avocado-boot.conf "${SERIAL_CONSOLES}" ${D}/boot/loader/entries/avocado.conf
    chmod 0644 ${D}/boot/loader/entries/avocado.conf
}

inherit deploy

do_deploy() {
    :
}

do_deploy:arm64-uefi() {
    install -D ${S}/avocado-loader.conf ${DEPLOYDIR}/loader.conf
    avocado_arm64_boot_entry ${S}/avocado-boot.conf "${SERIAL_CONSOLES}" ${DEPLOYDIR}/avocado.conf
}

addtask deploy after do_install
