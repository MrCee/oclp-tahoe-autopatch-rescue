# Validation and limits

Hardware results for Autopatch Rescue, and the automated checks behind it.

## 2026-11-05: OCLP RC5 + Tahoe 26.7.2 with Autopatch Rescue

Same mid-2014 **MacBookPro11,3**. The USB was created on an iMac18,2 with the official **OCLP 3.0.0-rc.5** app: *Create macOS Installer* (Tahoe **26.7.2, 25G332**), then *Build and Install OpenCore* for MacBookPro11,3 onto the USB.

| Check | Result |
| :--- | :--- |
| USB as OCLP left it | No `Library/Packages` (no `AutoPkg-Assets.pkg`, no `KDK.pkg`); DataHub `SystemProductName`/`BoardProduct` empty, `UpdateDataHub` false. OCLP log: `Stock Install.pkg is missing on Github`, `Downloaded size: 495.0 B`. |
| `autopatch_rescue.py` | Added RC5 `AutoPkg-Assets.pkg` (`a965871a…`) and Apple `KDK.pkg` for 25G332 from `Kernel_Debug_Kit_26.7.2_build_25G332.dmg` (`9490bd9b…`); set DataHub to `MacBookPro11,3` / `Mac-2BD1B31983FE1663` / `UpdateDataHub = true` with a config backup; ended with `PASS`. |
| Install on the MacBook | Booted through USB EFI, installed Tahoe 26.7.2. **No "failed to obtain model information" loop.** The owner reports the installation works. |

**Limits:** all three fixes were applied together, so this doesn't show which one was essential on RC5 by itself. The packages are needed by mechanism (no OCLP to auto-patch without the assets package; Modern Audio needs the KDK offline). DataHub was then tested on its own (next section).

## 2026-11-05: control test with DataHub left blank

Same USB and same MacBookPro11,3. Only the OpenCore config was changed: OCLP's original was put back (`DataHub/SystemProductName` and `BoardProduct` empty, `UpdateDataHub` false). Both packages stayed on the USB.

| Step | Result |
| :--- | :--- |
| Boot USB EFI → installer, DataHub blank | **Immediate loop on "failed to obtain model information".** Repeated on every proper boot (Option → the USB's EFI Boot). |
| Put DataHub back with the published `autopatch_rescue.py` (fresh clone of `main`) | Detected `DataHub: MISSING`, set `MacBookPro11,3` / `Mac-2BD1B31983FE1663` / `UpdateDataHub = true`, backed up the blank config, ended with `PASS`; packages untouched. |
| MacBook afterwards | Looped at first, then started normally after two restarts. The internal SSD had been fully formatted before these tests. |

**Conclusion:** on this MacBookPro11,3 with OCLP 3.0.0-rc.5 and Tahoe 26.7.2, the DataHub model and board ID are required. With them blank the USB can't boot; with them filled in, the same USB installed Tahoe successfully. A boot from the USB after the published script restored them was not repeated in this session.

## Automated checks

### 2026-11-06: initial restored RC5 desktop finisher

`finish_install.py` is now standalone and accepts installed Tahoe 26 on
MacBookPro11,3, including **RC5 / 26.7.2 / 25G332**. It is no longer pinned to
the retired RC3 build 25G241 or dependent on its deleted modules. The only EFI
changes are the three DataHub values. At that initial revision, USB preparation
supplied the small finishing bundle for an unspoofed MacBookPro11,3 build.

The restored tool and launcher are checked with fixtures for internal-disk
selection, backups/read-back, conflicting settings, missing boot files,
read-only audit mode, bundle integrity, and prerequisite-tool handling. A
read-only disk-selection check also followed the preparation iMac's running
APFS snapshot to its physical disk successfully; invoking the full helper on
that iMac stopped at the wrong-model guard before mounting or editing EFI.

**MacBook hardware evidence, 6 November:** the owner supplied the standalone
helper's terminal output from **MacBookPro11,3 / Tahoe 26.7.2 / 25G332**. Its
initial read-only audit identified the internal EFI and found empty
`SystemProductName` and `BoardProduct`, with `UpdateDataHub = false`. OpenCore
and root patches were reported installed. The normal finisher then reported
its backup/report location and `PASS: internal EFI configuration verified`.
The owner subsequently reported that `--check` showed the expected values.
These are owner-supplied results; the preparation iMac did not independently
read the MacBook's internal config. [Detailed evidence and source analysis](INTERNAL-DATAHUB.md).

**Owner-reported outcome:** the owner now reports that the MacBook works after
the internal DataHub correction and identifies the desktop finisher as the
final step that wrote those values. The exact number of successful
starts/restarts and a detailed boot transcript have not been supplied. The
configuration verification is supported by the supplied helper output; the
working-system result is owner-reported, without independent boot observation
or a claim of repeated stability. The bundled TXT asks for an audit of the
existing internal config **before** rebuilding OpenCore or applying changes.

### 2026-11-06: generic model-aware revision

The current bundle is **`OCLP-Finish/`**. It includes `oclp_models.json` and an
integrity manifest, reads the installed internal config's `OCLP-Model`, checks
`#Revision/Original-Model`, and compares that target with the running Mac's
reported/original-model evidence. The board ID comes from the existing OCLP
model table, rather than a hardcoded MacBookPro11,3 constant or a fixed target
in the bundle manifest. An inconsistent or unknown model stops before any edit.

When a correction is needed, the interactive tool offers to use the detected
matching target or stop to change Target Model and rebuild in OCLP. A mismatch
or spoofed config is refused; changing only three DataHub values cannot retarget
the other model-specific parts of an EFI. `--check` remains read-only and
`--yes` skips only the confirmation question. Already correct settings are left
unchanged without creating another configuration backup/report.

Fixtures cover multiple model lookups, wrong-target and unknown-model refusal,
original-model hints, confirmation/decline, the generic bundle and preservation
of historical `MBP113-Finish/` files. The launcher setup-log template now ends
in `X` placeholders so macOS generates unique names on repeat runs.

**Hardware scope:** the reported working result above belongs to the original
MacBookPro11,3-specific bundle. The generic revision has not been run against a
real internal EFI in this session, and no boot result on another model is
claimed. The preparation Mac's model table and scoped original-model NVRAM hint
were read successfully without mounting or editing EFI.

```bash
./scripts/test.sh
```

| Suite | Checks | Method |
| :--- | ---: | :--- |
| Autopatch Rescue | 38 | Fake installer USB, EFI and GitHub releases; no network, disk images or real disks. Covers adding both packages, skipping correct files, `--check` without writes, deleting wrong packages, cached downloads and partial copies before re-downloading, corrupt and HTML-error downloads, missing digests, a missing KDK release and `--kdk-build`, an unsigned KDK, internal or non-installer volumes, pre-Big Sur installers, low space, reading the OCLP tag, and the EFI DataHub step (filling empty values from the built model, board ID per model, keeping correct or spoofed configs, refusing to overwrite conflicting values or non-OCLP configs, `--check` and `--packages-only`), the summary report, the confirmation question (answering no changes nothing; no terminal without `--yes` changes nothing), and restoring the desktop bundle without rewriting correct USB settings or packages. |
| Desktop bundle/launcher | 14 | Temporary folders and stubbed tools; no real installation. Checks hashes, bundled model data, backups, retained logs, symlinks, stable exact CLT package selection, audit mode without Python, Tahoe guards, option forwarding, unique setup-log names and retention of the old model-specific folder. |
| Internal EFI finisher | 32 | Simulated APFS systems and EFI files; no real EFI writes. Checks the running system's physical disk, multiple model lookups, original-model hints, unknown/mismatched targets, confirmation/decline, conflicting/spoofed settings, enabled boot files, backups, atomic writes, read-back, repeat runs and read-only audit behavior. |

## Not covered

- Other Mac models on real hardware. The packages are missing from every RC-built USB whatever the model; the DataHub fix has only been proven on the MacBookPro11,3.
- Final OCLP releases after 3.0.0; `--check` will show whether they need anything.
