# i.MX93 AHAB: SRK PKI generation and signing

How the root of trust for `avocado-imx93-frdm` is generated, where the keys
live, and what the build still has to grow before a signed `flash.bin` exists.

Nothing here is wired up yet. This documents the intended flow and records the
findings that contradict the obvious approach, so the next person does not
spend a day on a variable that does nothing.

Sources: `doc/imx/ahab/introduction_ahab.txt` and
`doc/imx/ahab/guides/mx8ulp_9x_secure_boot.txt` in u-boot-imx 2026.04, which is
what this machine builds.

## What the build already has

`imx-cst` 3.4.1 is in `meta-openembedded/meta-oe/recipes-support/imx-cst/`, and
`meta-oe` is already a layer here (`kas/base.yml`). The recipe carries
`BBCLASSEXTEND = "native nativesdk"` and installs `cst`, `srktool` and
`csf_parser`, and its own description says it "integrates the HABv4 and AHAB
library". So `imx-cst-native` needs no new recipe, no bbappend, and no layer
addition - it is available to any recipe that puts it in `DEPENDS`.

## What the build does not have

**No AHAB container signing exists anywhere in the layer stack.** Nothing calls
`cst` or `srktool`. Three variables look like they might be the switch and none
of them is:

- `UBOOT_SIGN_ENABLE` is the FIT/HABv4 u-boot signing path. In
  `meta-freescale/recipes-bsp/imx-mkimage/imx-boot_1.0.bb` it is referenced
  only inside `compile_mx8m()`. `compile_mx93()` does not mention it. Setting
  it on this machine does nothing.
- `SECO_FIRMWARE_NAME` is the ELE firmware blob NXP signs and ships
  (`mx93${REV}-ahab-container.img`). It is required to boot at all, signed or
  not, and is not a secure-boot toggle.
- `SECOEXT_FIRMWARE_NAME` names an *extended* ELE runtime container. Upstream
  defines it only for mx8ulp, mx95 and mx943 (`imx-base.inc:507-510`); for mx93
  it is empty, which is why `avocado-imx-frdm.inc` carries the one-line
  `SECOEXT_FIRMWARE_NAME ?= "none"` shim. Its only consumer,
  `firmware-ele-imx_2.0.5.bb`, is `COMPATIBLE_MACHINE = "avocado-imx95-frdm"`,
  so on i.MX93 the value is inert. Replacing `"none"` with a container name
  does not enable AHAB; there is no mx93 value to replace it with.

`CONFIG_AHAB_BOOT` is also off. Read from the produced config, not the
defconfig:

```console
$ grep AHAB build/tmp/work/avocado_imx93_frdm-*/u-boot-imx/2026.04/build/imx93_11x11_frdm_defconfig-sd/.config
# CONFIG_AHAB_BOOT is not set
```

That option is what lets SPL and U-Boot extend the root of trust through the
ELE API and read the AHAB event log. Without it there is no `ahab_status` to
validate a signed image with.

## Generating the PKI tree

Run once, off the build machine, on a host that will hold the private keys. The
CST tarball ships the generator under `keys/`.

```bash
./ahab_pki_tree.sh
  Do you want to use an existing CA key (y/n)?: n
  Do you want to use Elliptic Curve Cryptography (y/n)?: y
  Enter length for elliptic curve to be used for PKI tree: p384
  Enter the digest algorithm to use: sha384
  Enter PKI tree duration (years): 5
  Do you want the SRK certificates to have the CA flag set? (y/n)?: n
```

This yields one CA and four SRKs. Four is the hardware's count - the SRK table
holds four keys and the fuses hold the hash of that table, so a compromised or
expired SRK is revoked by switching to another of the four rather than by
re-fusing. Answering `y` to the CA-flag question instead produces a subordinate
SGK under each SRK, which keeps the SRK private keys offline at the cost of a
second key tier. Start without SGK; adding it later changes the CSF, not the
fuses.

## SRK table and fuse hash

**This is the step that is easy to get wrong by copying an i.MX8 example.**
i.MX 8/8x expect a 512-bit SRK hash; i.MX 8ULP and 9x expect **256-bit**. The
i.MX93 command therefore needs `-d sha256` in addition to `-s sha384`:

```bash
cd ../crts/
../linux64/bin/srktool -a -d sha256 -s sha384 \
    -t SRK_1_2_3_4_table.bin \
    -e SRK_1_2_3_4_fuse.bin -f 1 -c \
    SRK1_sha384_secp384r1_v3_usr_crt.pem,\
    SRK2_sha384_secp384r1_v3_usr_crt.pem,\
    SRK3_sha384_secp384r1_v3_usr_crt.pem,\
    SRK4_sha384_secp384r1_v3_usr_crt.pem
```

Omitting `-d sha256` produces a table whose hash will never match what the
i.MX93 ELE computes, and the failure only shows after the fuses are burned -
which is irreversible. Regenerate and cross-check the fuse value before going
anywhere near a fuse:

```bash
openssl dgst -binary -sha256 SRK_1_2_3_4_table.bin | od -t x4 --endian=big
od -t x4 --endian=big SRK_1_2_3_4_fuse.bin
```

The two must match. `SRK_1_2_3_4_table.bin` ships inside the signed image;
`SRK_1_2_3_4_fuse.bin` is what gets burned.

## Key custody

Nothing under `crts/` in private-key form, and nothing under `keys/`, may be
committed to this repo or any other. That includes the CA key, which is what
would let an attacker mint a fifth SRK.

Only the public artifacts belong in a build: `SRK_1_2_3_4_table.bin` (embedded
in the image) and the SRK public certificates the CSF references. The signing
step needs the private keys, so it either runs on a host that holds them or the
build hands the container off to a signing service. Which of those we do is
open - see the signing-infrastructure question in the Secure Boot project. The
`sb-keys.bb` recipe already solves the adjacent reproducibility problem for
UEFI keys with `BB_BASEHASH_IGNORE_VARS`, and the same pattern applies to
whatever variable points at the SRK directory.

## Prior art: meta-variscite-hab

Variscite ships a working AHAB integration for this SoC family on the same
Yocto release and the same NXP BSP tag we build (`wrynose`, i.MX
6.18.20-2.0.0). It is worth reading before writing any of the below, because it
answers the hard part differently than the NXP guide implies.

`varigit/meta-variscite-hab` at `wrynose_var01`, ~24 files. What is directly
reusable:

- **`imx_signer` removes the offsets problem entirely.** It is
  `varigit/nxp-cst-signer` at `v3.0_var01`, a fork of NXP's `cst_signer`, and
  it parses the container to locate the header and signature block itself:
  `imx_signer -d -i <imx-boot-...-sd.bin> -c <config>` emits
  `signed-<image>`. No CSF generation from build logs, and no two-pass split of
  `do_compile`.
- **SPSDK rather than CST for the AHAB path.** The config is a YAML, not a CSF.
  Their `mx93-generic-bsp/spsdk_ahab.yaml` is `family: mimx9352`,
  `srk_set: oem`, `used_srk_id: 0`, `hash_algorithm: sha384`, `flag_ca: false`,
  signing with `SRK1_sha384_secp384r1_v3_usr_key.pem` - which matches the P-384,
  no-SGK tree recommended above. Note that SPSDK is expected on the host:
  `spsdk.bbclass` fails the build when `${SIG_TOOL_PATH}/spsdk` is absent, it
  does not build it. `imx-cst-native` is only used on their HABv4 path.
- **Fuse commands are generated, not typed.** `mx8-fuse-commands-helper.bbclass`
  reads the SRK fuse binary and emits a U-Boot script, deployed next to the
  image. For i.MX93 (`create_fuse_cmds_mx9`) that is one
  `fuse prog -y 16 <word> <value>` line per word for words 0-7 - eight 32-bit
  words, confirming the 256-bit hash above - followed by `ahab_close`.
  Generating these beats transcribing them by hand when each line is
  irreversible.
- **The kernel gets its own signed container.**
  `linux-var-ahab-signature.inc` assembles one by calling `mkimage_imx8` with
  `-soc IMX9 -c -ap Image a55 0x80400000 --data <dtb> a55 0x83000000`, signs it
  to `os_cntr_signed.bin`, and ships it as `kernel-image-signed`, which
  `layer.conf` makes essential under the `ahab` override. That is the
  root-of-trust extension from SPL through to Linux.
- **`ahab` as an override**, with bbappends gated on
  `'ahab' in d.getVar('OVERRIDES')`, is how they scope all of it.

They also confirm `CONFIG_AHAB_BOOT=y` is the required u-boot symbol, though
they set it by appending to `${B}/${config}/.config` in `do_compile:prepend`
rather than through a config fragment.

**One thing not to copy.** `var-hab-certs.bb` fetches a *public* certificate
repo and hardcodes `CST_KEYPASS ?= "Variscite_password"` and
`CST_SERIAL ?= "1248163E"`. Those are demo keys, and they are `?=` so a product
is expected to override them - but a device fused against that default SRK hash
has secure boot that anyone can satisfy. Whatever we build must fail closed when
no key is configured rather than fall back to a shipped default.

Worth noting for scope: their manifest carries `meta-security`, but nothing in
their layers consumes it - no IMA policy, no dm-verity. A vendor doing this work
seriously on the same silicon chose signed containers over runtime appraisal.

## Why the raw CST path needs generated offsets

The AHAB signature lives inside the container, and `cst` is told which byte
ranges to sign by explicit offsets in the CSF:

```ini
[Authenticate Data]
File = "u-boot-atf-container.img"
# Offsets = Container header   Signature block
Offsets   = 0x0                0x110
```

Those offsets come from `imx-mkimage`'s own stdout at build time:

```text
CST: CONTAINER 0 offset: 0x0
CST: CONTAINER 0: Signature Block: offset is at 0x110
```

They move whenever the images inside the container change size, which is every
build. So a checked-in CSF with hardcoded offsets signs the wrong bytes as soon
as U-Boot grows, and it fails at boot rather than at build. The Yocto
integration has to capture the mkimage log and generate the CSF from it.

It is also a **two-pass** build, because the inner container must be signed
before the outer one is assembled:

1. `make SOC=<soc> u-boot-atf-container.img` - note the offsets
2. `cst -i csf_uboot_atf.txt -o signed-u-boot-atf-container.img`
3. copy the signed file back over `u-boot-atf-container.img` in the target dir
4. `make SOC=<soc> flash_<bootmode>` - note the **new** offsets
5. `cst -i csf_boot_image.txt -o signed-flash.bin`

`imx-boot_1.0.bb` runs steps 1 and 4 inside one `do_compile`, so a raw-CST
integration has to split them or drive mkimage twice.

CSF templates for that path are in u-boot-imx under
`doc/imx/ahab/csf_examples/` - `csf_uboot_atf.txt` for the inner container and
`csf_boot_image.txt` for `flash.bin`.

**Prefer `cst_signer` over doing this by hand.** It reads the offsets out of
the container rather than out of a build log, which is what makes the whole
step a single call on the finished `imx-boot` artifact. The section above
describes the mechanism only so that a failure inside the tool is debuggable.

## Order of operations on hardware

The part ships **open**: it will boot an unsigned image, and it will also boot a
signed one without checking it. That is the window to validate in.

1. Build a signed `flash.bin` and boot it on an open board.
2. Read the AHAB event log (`ahab_status` in U-Boot, which needs
   `CONFIG_AHAB_BOOT=y`). It must report zero authentication events.
3. Only then burn `SRK_HASH`.
4. Only after a signed image boots on a fused part, close the device.

Steps 3 and 4 are irreversible and brick the board if anything earlier was
wrong. They must never run as part of a normal provision - see the
irreversible-action confirmation requirement tracked with the rest of the
OTP-fusing safety rails.
