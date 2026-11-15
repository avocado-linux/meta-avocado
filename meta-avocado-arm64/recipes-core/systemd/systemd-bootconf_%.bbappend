FILESEXTRAPATHS:prepend:arm64-uefi := "${THISDIR}/files:"

SRC_URI:append:arm64-uefi = " file://avocado-boot.conf file://avocado-loader.conf"

# Write the boot entry $1 to $3 with one console=<tty>,<baud>n8 per
# SERIAL_CONSOLES entry ($2) appended to its options line. The entry's
# console=tty0 sets console_set_on_cmdline, and the kernel then skips the
# device-tree stdout-path UART as a console, so on a device-tree platform the
# kernel goes silent once the early console is disabled. An ACPI machine keeps
# its UART because the SPCR table adds it regardless. An empty list copies the
# entry unchanged. A malformed entry, or a list with no options line to carry
# it, fails: a silent success would leave the console silent. POSIX only, and
# no braced expansions in here: BitBake would expand them at parse time.
# Inputs are arguments so the host test can run it.
avocado_arm64_boot_entry() {
    abe_src=$1
    abe_args=
    # Word splitting on whitespace is the SERIAL_CONSOLES list syntax. Pathname
    # expansion stays off while the list is split, so a glob character is
    # rejected by the checks below instead of matching a file in the cwd.
    set -f
    # shellcheck disable=SC2086
    for abe_entry in $2; do
        abe_baud=$(printf '%s\n' "$abe_entry" | cut -d ';' -f 1)
        abe_tty=$(printf '%s\n' "$abe_entry" | cut -d ';' -f 2)
        abe_ok=
        # A baud is digits with at least one non-zero digit, and a tty name is
        # letters, digits and underscores. An entry with no semicolon has no
        # second field, and cut then returns the whole entry as the tty.
        case $abe_entry in
            *';'*)
                case $abe_baud in
                    '' | *[!0-9]*) ;;
                    *[1-9]*) abe_ok=1 ;;
                esac
                case $abe_tty in
                    '' | *[![:alnum:]_]*) abe_ok= ;;
                esac
                ;;
        esac
        if [ -z "$abe_ok" ]; then
            set +f
            printf "avocado_arm64_boot_entry: malformed SERIAL_CONSOLES entry '%s', expected <baud>;<tty> with a baud above zero and a tty name of letters, digits and underscores\n" "$abe_entry" >&2
            return 1
        fi
        abe_args="$abe_args console=$abe_tty,$abe_baud""n8"
    done
    set +f
    if [ -z "$abe_args" ]; then
        cp "$abe_src" "$3"
        return 0
    fi
    abe_hit=
    while true; do
        if IFS= read -r abe_line; then
            abe_end=1
        elif [ -n "$abe_line" ]; then
            abe_end=
        else
            break
        fi
        case $abe_line in
            'options '*)
                abe_line="$abe_line$abe_args"
                abe_hit=1
                ;;
        esac
        if [ -n "$abe_end" ]; then
            printf '%s\n' "$abe_line"
        else
            printf '%s' "$abe_line"
            break
        fi
    done < "$abe_src" > "$3"
    if [ -z "$abe_hit" ]; then
        rm -f "$3"
        printf "avocado_arm64_boot_entry: no 'options ' line in %s to carry the console arguments\n" "$abe_src" >&2
        return 1
    fi
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
