# OCLP Tahoe Autopatch Rescue

![OCLP: 3.0.0 RC](https://img.shields.io/badge/OCLP-3.0.0--rc.5-f59e0b)
![macOS: Tahoe 26](https://img.shields.io/badge/macOS-Tahoe%2026-111827)
![Any OCLP Mac](https://img.shields.io/badge/model-any%20OCLP%20Mac-2563eb)

**If you've landed here, OCLP's normal process didn't work for you.** You made a Tahoe installer USB with an OCLP 3.0.0 release candidate, installed macOS from it, and either the Mac got stuck in a boot loop or nothing was patched afterwards (no Wi-Fi, graphics acceleration or audio).

Autopatch Rescue fixes the **USB installer**. You then use the fixed USB to install Tahoe onto a clean, formatted drive. For a known, unspoofed target model, it also puts the generic internal-EFI tool in **`OCLP-Finish/`** on the USB.

**Already reaching the installed Tahoe desktop through USB EFI? Go straight to [Finish internal OpenCore](#finish-internal-opencore).** Keep your installed system; this final step does not require erasing or reinstalling Tahoe.

## What it fixes

- **Missing `AutoPkg-Assets.pkg` and `KDK.pkg`.** OCLP is meant to put these on the USB, so that after macOS installs, OCLP installs itself and root patches automatically. A bug in every 3.0.0 release candidate leaves them off and still reports success. [Why this happens](docs/OCLP-RC-ASSETS-BUG.md).
- **Missing OpenCore DataHub model and board ID.** Without them, a Mac can loop at boot on "failed to obtain model information". OCLP only fills these in for some Macs ([details below](#when-datahub-is-written)).

Everything else OCLP built is left exactly as it is.

## Before you start

- **For a fresh installation, plan a clean install.** Back up the target Mac. You'll erase its drive during the install. An existing installed desktop can proceed to the internal-EFI audit below.
- On the Mac you're preparing the USB on, in OCLP:
  1. Set **Settings → Target Model** to the Mac you'll install on.
  2. Turn on **Verbose** in the build settings (off by default), so a boot loop shows on screen.
  3. Run **Create macOS Installer** and write Tahoe to the USB.
  4. Run **Build and Install OpenCore** onto the USB.
- You need Python 3.9+, internet access, and about 2.2 GB free on the USB.

## Fix the USB

With the USB still plugged in:

```bash
git clone https://github.com/MrCee/oclp-tahoe-autopatch-rescue.git
cd oclp-tahoe-autopatch-rescue
python3 autopatch_rescue.py --usb "/Volumes/Install macOS Tahoe"
```

What happens:

1. It **asks for your Mac password**, which it needs to open the USB's EFI partition.
2. It **shows what the USB is for:** the macOS version, the OCLP release, and the Mac OpenCore was built for, by name and model identifier.
3. It **checks** `AutoPkg-Assets.pkg`, `KDK.pkg` and the DataHub values, and shows each as OK or MISSING.
4. If something is missing, it **asks you to confirm** that this is the Mac you're installing on. Answer `n` and nothing is changed.
5. It **fixes only what's missing**, then checks again and ends with `PASS`.
6. For an unspoofed build with a model in the bundled table, it also copies and verifies **`OCLP-Finish/`** on the USB. This is the separate desktop step for preserving the model fix after installing OpenCore internally.

For example, on a USB straight from an OCLP release candidate (the Mac shown is just an example):

```text
This USB
  macOS installer:     Tahoe 26.7.2 (25G332)
  OCLP release:        3.0.0-rc.5
  OpenCore built for:  iMac (Retina 4K, 21.5-inch, 2017) (iMac18,2)
  Verbose boot:        on

Checks
  AutoPkg-Assets.pkg   MISSING -> download from OCLP 3.0.0-rc.5
  KDK.pkg              MISSING -> add Apple KDK for 25G332
  DataHub              MISSING SystemProductName, BoardProduct, UpdateDataHub -> set iMac18,2, Mac-77F17D7DA9285301, UpdateDataHub on

This USB is set up for: iMac (Retina 4K, 21.5-inch, 2017) (iMac18,2)
Is that the Mac you're installing on, and should the changes above be made? [y/N]
```

Options: `--check` reports without changing anything, `--yes` skips the question, and `--packages-only` skips the EFI check and desktop-tool bundle. If you rebuild USB OpenCore in OCLP later, run the script again. After rebuilding **internal** OpenCore, audit the desktop final tool’s detected target and DataHub settings before rebooting.

**How the packages are handled:** the assets package comes from the OCLP release you have installed, and the KDK from Dortania's KdkSupportPkg for your installer's macOS build. Both downloads are checked against the SHA-256 digests GitHub publishes, and the `KDK.pkg` taken from the KDK disk image must be Apple-signed. A package already on the USB that doesn't match is deleted and downloaded again, never edited. Nothing is installed on the Mac you run the script on.

### When DataHub is written

The script reads the OpenCore config on the USB's EFI (`EFI/OC/config.plist`) every time it runs:

| What it finds | What it does |
| :--- | :--- |
| No OpenCore, or a config OCLP didn't build | **Stops.** Run *Build and Install OpenCore* in OCLP first. |
| OCLP built it **spoofed** as another model | **Leaves it alone.** OCLP has already set DataHub for that model. |
| Model, board ID and `UpdateDataHub` already set correctly | **Changes nothing.** |
| Model or board ID **empty**, or `UpdateDataHub` off | **Writes only what's missing:** the model OCLP built for, that model's board ID from OCLP's own model table ([`oclp_models.json`](oclp_models.json)), and `UpdateDataHub = true`. It backs up the config first. |
| A **different** value is already there | **Stops without overwriting**, so you can check it. |

**Why it can be missing:** OCLP fills in the DataHub board ID itself to prevent this boot loop, but only on Ivy Bridge and older Macs (roughly 2012 and earlier), or when you build with SMBIOS spoofing. A newer Mac built as itself gets both values empty. The script only ever writes the Mac's own real values, so it's safe on Macs that would have booted without them.

## Install on the target Mac

1. Plug the fixed USB into the Mac you built it for. Hold **Option** at power-on and choose the USB's **EFI Boot**, then **Install macOS Tahoe**.
2. **Erase the drive:** open **Disk Utility** from the installer, erase the target drive (APFS; choose GUID Partition Map if you erase the whole disk), then quit Disk Utility and install Tahoe onto it.
3. At **every restart**, hold Option and choose the USB's **EFI Boot** again: the **macOS Installer** entry while installing, then **Macintosh HD** once it's finished.
4. Near the end, the installer runs the two packages: OCLP installs itself, root patches, and restarts once more. Afterwards, OCLP's *Post-Install Root Patch* screen should show today's date.
5. Finish the internal OpenCore setup below before attempting to boot without the USB.

## Finish internal OpenCore

The final tool is model-aware and supports matching, unspoofed **OCLP 3.0.0 RC5 / installed Tahoe 26** configurations whose real model and board ID are present in the bundled [`oclp_models.json`](oclp_models.json). It detects the internal OpenCore target and compares it with the running Mac before offering a correction. **Hardware evidence is from MacBookPro11,3 only; other models have fixture coverage, not a confirmed boot result.**

**Why the internal step is needed:** on the tested MacBook, the USB's DataHub settings were correct, but the internal EFI still had empty model/board values and `UpdateDataHub = false` after internal OpenCore installation. RC5 installs a newly generated OpenCore build; it does not automatically carry over the USB's manual DataHub edits. The standalone finisher changes just those three internal settings. If Tahoe, OpenCore and the required root patches are already installed, this correction does not require preparing another USB or reinstalling macOS. See the [developer evidence and proposed builder fix](docs/INTERNAL-DATAHUB.md).

**Owner-reported result, 6 November:** the MacBook now works after the internal DataHub correction. The exact number of successful starts/restarts has not been recorded; this is a reported result on one MacBookPro11,3.

1. Boot **USB EFI Boot → your installed Tahoe disk** and reach the desktop. Choose the installed disk, rather than starting the installer again. Keep the USB connected and writable.
2. Open **`OCLP-Finish/READ-ME-FIRST.txt`** on the USB. **Check before rebuilding or changing anything:**

   ```bash
   /bin/bash "/Volumes/Install macOS Tahoe/OCLP-Finish/finish-install.command" --check
   ```

   This reports the current internal EFI and DataHub values. The USB's corrected config is separate: macOS installation does not transfer it to the internal EFI. The check mounts an unmounted EFI read-only, makes no config edits, and does not install developer tools. If Python is missing, the TXT includes a Codex handover for inspecting the same settings with native macOS tools first.
3. If internal OpenCore is missing or needs replacing, open **OCLP 3.0.0 RC5**, set **Target Model** to the Mac being installed, and choose **Build and Install OpenCore**. Install to the **internal physical drive containing your running Tahoe system**, then its **EFI partition**. Identify the internal drive by its name and capacity; do not assume a disk number. **Wait before accepting OCLP's reboot prompt.** If existing internal OpenCore is suitable and only DataHub needs fixing, proceed without rebuilding. Post-Install Root Patch and installing internal OpenCore are separate steps.
4. When the audit reports missing DataHub settings, or after installing internal OpenCore, double-click **`finish-install.command`**, or run:

   ```bash
   /bin/bash "/Volumes/Install macOS Tahoe/OCLP-Finish/finish-install.command"
   ```

   Enter this Mac’s administrator password when asked. Confirm the displayed Mac, installed OpenCore target and board ID before choosing to use that target. Choosing **change model** stops with instructions to select the correct Target Model and rebuild/install in OCLP; the finisher does not retarget a model-specific EFI by changing DataHub alone. No Git clone is needed. The launcher reuses Python 3.9+ if available. If it is unavailable, it discovers and installs only the newest stable **Command Line Tools for Xcode** package Apple offers for this Mac, then checks Python again; this prerequisite download needs internet. It does not select a macOS upgrade. A failed prerequisite setup stops before any EFI edit. `--check` never installs developer tools.
5. Require **`PASS: internal EFI configuration verified`**. Shut down, remove the USB, start holding **Option**, then choose the **internal EFI Boot → your Tahoe disk**. Confirm a usable desktop and test an ordinary restart without the USB. Keep the USB as the fallback if the test fails.

The helper follows the **currently running internal APFS system** to its physical disk and existing OpenCore EFI. It reads that config’s `OCLP-Model`, cross-checks `#Revision/Original-Model`, compares it with the running Mac’s model evidence, and looks up the board ID in the bundled model table. The integrity manifest checks the bundled files; it does not choose the hardware identity. The tool checks referenced boot files, saves the original config, applies only these settings, and reads the result back:

| Setting in the internal `EFI/OC/config.plist` | Value |
| :--- | :--- |
| `PlatformInfo/DataHub/SystemProductName` | Verified installed target matching this Mac |
| `PlatformInfo/DataHub/BoardProduct` | That model’s board ID from `oclp_models.json` |
| `PlatformInfo/UpdateDataHub` | `true` |

Correct settings are left unchanged without a confirmation prompt or config write. Unknown models, hardware/target mismatches, conflicting values and spoofed/automatic configurations stop for review. `--yes` accepts a matching detected target for automation; it never bypasses those checks. The helper does not install OpenCore, root-patch, erase, reboot or change boot arguments. An absent internal OpenCore installation stops with instructions to install it first. Backups and reports are under **`OCLP-Finish/build/internal-efi/`** on the USB; a config backup is also saved beside the internal EFI config. Setup logs are under `OCLP-Finish/build/bootstrap/`.

To audit without editing the internal config, append `--check` to the launcher command. **After rebuilding internal OpenCore, rerun the final tool before rebooting**, because OCLP can replace the DataHub correction.

If the boot test fails, reconnect the USB and boot **USB EFI Boot → the installed Tahoe disk**. Keep the error and report. A passing configuration check confirms the files and settings; a successful USB-free start and ordinary restart must still be tested on the target Mac.

**Older USBs:** an existing `MBP113-Finish/` folder remains the historical MacBookPro11,3 bundle. New preparation writes `OCLP-Finish/` and leaves the old folder and logs untouched. Use the new folder after updating; the old tested bundle remains usable for that original MacBook.

## Troubleshooting

| Situation | What to do |
| :--- | :--- |
| `Library/Packages` on the USB is missing or empty | Run the script. |
| "failed to obtain model information" when starting the USB | Check the USB DataHub with `autopatch_rescue.py`; make sure you actually selected that USB's EFI Boot. |
| Installed system works through USB EFI but loops or fails without it | Audit internal OpenCore and its detected target, then correct missing DataHub settings when the target matches. |
| You use a final (non-RC) OCLP release | The package download works on final releases. Run `--check` to see whether anything else is missing. |
| The final 3.0.0 has been published | Update OCLP first. An RC app would then download the final release's assets, which don't match it. |

## Further information

- [Why OCLP RC USBs miss AutoPkg-Assets.pkg and KDK.pkg](docs/OCLP-RC-ASSETS-BUG.md): logs, source references and the fix.
- [Testing](docs/TESTING.md): hardware results, the DataHub control test and the automated checks.
- [Internal DataHub evidence](docs/INTERNAL-DATAHUB.md): RC5 before/after results, the fresh-build mechanism and the scope of an internal-only correction.
- [OCLP: booting without the USB drive](https://dortania.github.io/OpenCore-Legacy-Patcher/POST-INSTALL.html#booting-without-usb-drive).

This is an unofficial tool. **OCLP and its contributors provide the actual patches and boot support.** This repo provides surrounding code and documentation, developed with AI assistance. See [NOTICE.md](NOTICE.md) for upstream sources and credits, and [LICENSE](LICENSE).
