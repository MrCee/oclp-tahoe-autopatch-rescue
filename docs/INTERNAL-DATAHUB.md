# RC5 internal DataHub: observed omission and minimal correction

On the tested **MacBookPro11,3**, a correct USB EFI did not result in a correct
internal DataHub configuration after OCLP's internal OpenCore installation.
An internal-only correction is sufficient to write and verify those settings
on an otherwise installed system. Successful USB-free boots after the latest
correction remain to be tested.

## Evidence from 6 November 2026

Hardware: MacBookPro11,3; installed Tahoe **26.7.2 / 25G332**; OCLP **3.0.0 RC5**
workflow. The USB config was directly inspected on the preparation Mac and
contained the correct values. The MacBook owner reported OpenCore and root
patches installed, one successful start followed by the returning Lilu
model-information loop, and recovery to the installed desktop through USB EFI.

The owner then supplied this read-only finisher output from the MacBook:

```text
Running Mac: MacBookPro11,3 — macOS 26.7.2 (25G332)
Internal EFI: disk0s1 — /Volumes/EFI/EFI/OC/config.plist
DataHub/SystemProductName: ''
DataHub/BoardProduct: ''
PlatformInfo/UpdateDataHub: False
STOP: Internal EFI needs the DataHub fix. Run again without --check.
```

`disk0s1` is the identifier observed on this machine, not a disk number the
tool assumes or users should copy when selecting an installation target.

The owner next ran the finisher without `--check`. It identified the same
internal EFI, saved its backup/report and returned:

```text
PASS: internal EFI configuration verified; this is not a USB-free boot result.
```

The owner subsequently reported that another `--check` showed the expected
values. The full post-correction audit transcript has not been supplied.

| Internal config field | Before, supplied audit | After, verified by helper and follow-up reported by owner |
| :--- | :--- | :--- |
| `PlatformInfo/DataHub/SystemProductName` | Empty | `MacBookPro11,3` |
| `PlatformInfo/DataHub/BoardProduct` | Empty | `Mac-2BD1B31983FE1663` |
| `PlatformInfo/UpdateDataHub` | `false` | `true` |

This is terminal evidence from one MacBook, not an independent remote
inspection. There is no newly reported USB-free boot result after this edit.
The earlier successful start and later Lilu failure occurred before it.

## What the RC5 source does

RC5 builds a fresh OpenCore tree and config from its payload/template, applies
its builders and saves the result. See [base generation](https://github.com/dortania/OpenCore-Legacy-Patcher/blob/3.0.0-rc.5/opencore_legacy_patcher/efi_builder/build.py#L87-L109)
and [build/save sequence](https://github.com/dortania/OpenCore-Legacy-Patcher/blob/3.0.0-rc.5/opencore_legacy_patcher/efi_builder/build.py#L137-L152).

During installation, RC5 removes the destination's existing `EFI/OC` and
copies `EFI/OC` from that generated build. This path does not merge edits from
the USB EFI currently supplying the boot. A fresh internal installation can
therefore replace a manual correction with whatever the new build contains.
See [RC5 installation source](https://github.com/dortania/OpenCore-Legacy-Patcher/blob/3.0.0-rc.5/opencore_legacy_patcher/support/install.py#L111-L124).

The unspoofed SMBIOS branch already has a workaround for the Lilu board-ID
loop, but gates it to **Ivy Bridge and older**. MacBookPro11,3 is Haswell and
falls outside that condition. Other branches do set DataHub, so saying OCLP
"never writes DataHub" would be inaccurate. See [conditional workaround](https://github.com/dortania/OpenCore-Legacy-Patcher/blob/3.0.0-rc.5/opencore_legacy_patcher/efi_builder/smbios.py#L109-L118).

**Inference:** the observed blank internal values are consistent with a
configuration-generation omission. The evidence does not show that a copy
operation selectively dropped fields from an otherwise corrected build.
Lilu's model-information loop itself waits for model or board information;
it does not test whether a KDK is installed. See [Lilu model-information code](https://github.com/acidanthera/Lilu/blob/master/Lilu/Sources/kern_devinfo.cpp#L509-L589).

## Minimal workaround and proposed upstream direction

For an installed MacBookPro11,3 with valid internal OpenCore, the workaround
can be just an internal config edit. The standalone [finish_install.py](../finish_install.py)
does exactly that, with disk/model checks, backups and read-back verification.
It changes only the three tabled values. It does not require reinstalling
macOS, copying an entire personal USB EFI, downloading installer packages,
reinstalling root patches or changing boot arguments.

This does not replace the separate USB package preparation needed when an
installer is missing its automatic-patching assets or offline KDK. Those
dependencies address a different installation stage.

The proposed upstream direction is to review generating the appropriate real
DataHub values for the observed unspoofed MacBookPro11,3 configuration, so
both USB and internal builds receive them at build time. The three-value
workaround and the model's existing spoofing behavior need review; this
report does not justify applying it to every Mac or changing DataHub protocol
overrides.

The remaining hardware check is a successful internal-EFI start with the USB
disconnected, followed by an ordinary restart. If Lilu returns, preserve the
post-fix config and compare its hash/settings with the saved result while
investigating the actual EFI selected at the failing boot.
