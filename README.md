# OCLP Tahoe Autopatch Rescue

![OCLP: 3.0.0 RC](https://img.shields.io/badge/OCLP-3.0.0--rc.5-f59e0b)
![macOS: Tahoe 26](https://img.shields.io/badge/macOS-Tahoe%2026-111827)
![Any OCLP Mac](https://img.shields.io/badge/model-any%20OCLP%20Mac-2563eb)

**If you've landed here, OCLP's normal process didn't work for you.** You made a Tahoe installer USB with an OCLP 3.0.0 release candidate, installed macOS from it, and either the Mac got stuck in a boot loop or nothing was patched afterwards (no Wi-Fi, graphics acceleration or audio).

Autopatch Rescue fixes the **USB installer**. You then use the fixed USB to install Tahoe onto a clean, formatted drive.

## What it fixes

- **Missing `AutoPkg-Assets.pkg` and `KDK.pkg`.** OCLP is meant to put these on the USB, so that after macOS installs, OCLP installs itself and root patches automatically. A bug in every 3.0.0 release candidate leaves them off and still reports success. [Why this happens](docs/OCLP-RC-ASSETS-BUG.md).
- **Missing OpenCore DataHub model and board ID.** Without them, a Mac can loop at boot on "failed to obtain model information". OCLP only fills these in for some Macs ([details below](#when-datahub-is-written)).

Everything else OCLP built is left exactly as it is.

## Before you start

- **Plan a clean install.** Back up the target Mac. You'll erase its drive during the install.
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

Options: `--check` reports without changing anything, `--yes` skips the question, and `--packages-only` skips the DataHub step. If you rebuild OpenCore in OCLP later, run the script again.

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

## Troubleshooting

| Situation | What to do |
| :--- | :--- |
| `Library/Packages` on the USB is missing or empty | Run the script. |
| Boot loop on "failed to obtain model information" | Run the script on the USB, then do a clean install from it. |
| You use a final (non-RC) OCLP release | The package download works on final releases. Run `--check` to see whether anything else is missing. |
| The final 3.0.0 has been published | Update OCLP first. An RC app would then download the final release's assets, which don't match it. |

## Further information

- [Why OCLP RC USBs miss AutoPkg-Assets.pkg and KDK.pkg](docs/OCLP-RC-ASSETS-BUG.md): logs, source references and the fix.
- [Testing](docs/TESTING.md): hardware results, the DataHub control test and the automated checks.

This is an unofficial tool. **OCLP and its contributors provide the actual patches and boot support.** This repo provides surrounding code and documentation, developed with AI assistance. See [NOTICE.md](NOTICE.md) for upstream sources and credits, and [LICENSE](LICENSE).
