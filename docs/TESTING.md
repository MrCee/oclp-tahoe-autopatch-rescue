# Validation and limits

Hardware results for Autopatch Rescue, and the automated checks behind it.

## 2026-11-05: OCLP RC5 + Tahoe 26.7.2 with Autopatch Rescue

Same mid-2014 **MacBookPro11,3**. The USB was created on an iMac18,2 with the official **OCLP 3.0.0-rc.5** app: *Create macOS Installer* (Tahoe **26.7.2, 25G332**), then *Build and Install OpenCore* for MacBookPro11,3 onto the USB.

| Check | Result |
| :--- | :--- |
| USB as OCLP left it | No `Library/Packages` (no `AutoPkg-Assets.pkg`, no `KDK.pkg`); DataHub `SystemProductName`/`BoardProduct` empty, `UpdateDataHub` false. OCLP log: `Stock Install.pkg is missing on Github`, `Downloaded size: 495.0 B`. |
| `autopatch_rescue.py` | Added RC5 `AutoPkg-Assets.pkg` (`a965871a…`) and Apple `KDK.pkg` for 25G332 from `Kernel_Debug_Kit_26.7.2_build_25G332.dmg` (`9490bd9b…`); set DataHub to `MacBookPro11,3` / `Mac-2BD1B31983FE1663` / `UpdateDataHub = true` with a config backup; ended with `PASS`. |
| Install on the MacBook | Booted through USB EFI, installed Tahoe 26.7.2. **No "failed to obtain model information" loop.** The owner reports the installation works. |

**Limits:** all three fixes were applied together, so this doesn't show which one was essential on RC5 by itself. The packages are needed by mechanism (no OCLP to auto-patch without the assets package; Modern Audio needs the KDK offline). DataHub was then tested on its own (next section). Booting without the USB (internal OpenCore) was not part of this test.

## 2026-11-05: control test with DataHub left blank

Same USB and same MacBookPro11,3. Only the OpenCore config was changed: OCLP's original was put back (`DataHub/SystemProductName` and `BoardProduct` empty, `UpdateDataHub` false). Both packages stayed on the USB.

| Step | Result |
| :--- | :--- |
| Boot USB EFI → installer, DataHub blank | **Immediate loop on "failed to obtain model information".** Repeated on each proper boot (Option → the USB's EFI Boot). One earlier attempt behaved differently and wasn't counted; it most likely didn't start through the USB's OpenCore. |
| Put DataHub back with the published `autopatch_rescue.py` (fresh clone of `main`) | Detected `DataHub: MISSING`, set `MacBookPro11,3` / `Mac-2BD1B31983FE1663` / `UpdateDataHub = true`, backed up the blank config, ended with `PASS`; packages untouched. |
| MacBook afterwards, without the USB | Looped at first, then started normally after two restarts. The internal SSD had been fully formatted before these tests, so no older OpenCore was involved; the cause is not established. NVRAM written during the blank-DataHub boots is the likely candidate, and an NVRAM reset (Option-Command-P-R) clears such leftovers. |

**Conclusion:** on this MacBookPro11,3 with OCLP 3.0.0-rc.5 and Tahoe 26.7.2, the DataHub model and board ID are required. With them blank the USB can't boot; with them filled in, the same USB installed Tahoe successfully. A boot from the USB after the published script restored them was not repeated in this session.

## Automated checks

```bash
./scripts/test.sh
```

| Suite | Checks | Method |
| :--- | ---: | :--- |
| Autopatch Rescue | 36 | Fake installer USB, EFI and GitHub releases; no network, disk images or real disks. Covers adding both packages, skipping correct files, `--check` without writes, deleting wrong packages, cached downloads and partial copies before re-downloading, corrupt and HTML-error downloads, missing digests, a missing KDK release and `--kdk-build`, an unsigned KDK, internal or non-installer volumes, pre-Big Sur installers, low space, reading the OCLP tag, and the EFI DataHub step (filling empty values from the built model, board ID per model, keeping correct or spoofed configs, refusing to overwrite conflicting values or non-OCLP configs, `--check` and `--packages-only`), the summary report, and the confirmation question (answering no changes nothing; no terminal without `--yes` changes nothing). |

## Not covered

- Other Mac models on real hardware. The packages are missing from every RC-built USB whatever the model; the DataHub fix has only been proven on the MacBookPro11,3.
- Booting without the USB (OpenCore on the internal drive).
- Final OCLP releases after 3.0.0; `--check` will show whether they need anything.
