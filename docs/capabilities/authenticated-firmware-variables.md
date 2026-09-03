# `authenticated-firmware-variables`: the demo carve-out that permits unauthenticated variable storage must not extend to the authentication variables themselves; PK/KEK/db/dbx must be immutable at runtime even in a build using an unauthenticated store for everything else.

**Delivered by:** imx93-uefi-secureboot-enrollment
**Modules touched:** other

## Delivery Note

Invocation: `cat /run/avocado-boot-integrity` on a device built with `boot-integrity-poc` after this change, paired with `scripts/hitl/imx93-harness.sh --assert-signed-payload-refused` on the bench board
Precondition: the image carries `boot-integrity-poc`, PK/KEK/db were preseeded into U-Boot at build time via `CONFIG_EFI_VARIABLES_PRESEED`, and the staged EFI payload is signed against `db` from `AVOCADO_SB_KEYS_DIR`
Success signal: the record reads `enforcement=enabled` and `keydb_origin=firmware-resident` while `rot_state` remains `unauthenticated`, and the harness records a PASS for `signed_payload_refused` showing an unsigned payload was refused by `bootefi`
Silent failure: PK is enrolled but the payload is not actually signed against db, so the firmware reports `SecureBoot=1` while booting anything handed to it - enforcement claimed and not performed, which is the exact false confidence this whole line of work exists to prevent, and which task 7.3 exists to catch before it ships
