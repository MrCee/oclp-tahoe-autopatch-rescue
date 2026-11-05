# OCLP Tahoe Autopatch Rescue

![OCLP: 3.0.0 RC](https://img.shields.io/badge/OCLP-3.0.0--rc.5-f59e0b)
![macOS: Tahoe 26](https://img.shields.io/badge/macOS-Tahoe%2026-111827)
![Any OCLP Mac](https://img.shields.io/badge/model-any%20OCLP%20Mac-2563eb)

**If you've landed here, OCLP's normal process didn't work for you.** You built a Tahoe installer USB with an OCLP 3.0.0 release candidate, installed macOS, and either it got stuck in a boot loop or nothing was patched afterwards, so Wi-Fi, graphics acceleration or audio don't work.

**Autopatch Rescue is an alternative way to finish the USB installer.** Run it on the USB, then install again. It checks the USB and adds what the normal process should have put there:

- **`AutoPkg-Assets.pkg` and `KDK.pkg`.** OCLP 3.0.0 release candidates build USBs without them and still report success, so OCLP never installs itself or patches after the install. Seen with RC5; RC1, RC2 and RC3 contain the same download code. The assets package and the KDK disk image are downloaded from the official GitHub releases and checked against GitHub's published SHA-256 digests, and the `KDK.pkg` taken from the image must be Apple-signed.
- **The OpenCore DataHub model and board ID**, only if they're missing. Without them, a Mac can loop at boot on "failed to obtain model information" (OCLP calls this the Lilu race condition).

**Before you start:** plan on a **clean install**. Back up, then in the installer's Disk Utility **erase the target internal drive** (APFS, GUID Partition Map) before installing Tahoe from the adjusted USB. That's how this was tested.

```bash
git clone https://github.com/MrCee/oclp-tahoe-autopatch-rescue.git
cd oclp-tahoe-autopatch-rescue
python3 autopatch_rescue.py --usb "/Volumes/Install macOS Tahoe"
```

**The right order:** in OCLP, set **Settings → Target Model** to the Mac you'll install on, run **Create macOS Installer**, then **Build and Install OpenCore** onto the USB. *Then* run Autopatch Rescue on the same Mac, before you eject. It needs Python 3.9+, internet access and about 2.2 GB free on the USB.

### What the script does

1. **Asks for your Mac password**, which it needs to open the USB's EFI partition.
2. **Reads the USB and shows what it's for:** the macOS installer version, the OCLP release, and the Mac OpenCore was built for (by its name and model identifier). It also says whether Verbose boot is on.
3. **Checks three things** and shows each as OK or MISSING: `AutoPkg-Assets.pkg`, `KDK.pkg` and the DataHub values.
4. If something is missing, it **asks you to confirm** that this is the Mac you're installing on before changing anything. Answer `n` and nothing is touched. (`--yes` skips the question; `--check` only reports.)
5. **Fixes only what's missing:** it downloads the packages (checked against GitHub's published SHA-256 digests; the `KDK.pkg` must be Apple-signed) and writes the DataHub values (below). A package that doesn't match is deleted and downloaded again, never edited.
6. Checks again and ends with **`PASS: the USB is ready.`**

It leaves everything else OCLP built untouched, including OpenCore's kexts, patches and settings. Nothing is installed on the Mac you run it on.

Example: a USB made by an OCLP release candidate, before the fix (the Mac shown is just an example):

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

### When DataHub is written

Every time it runs, the script reads the OpenCore config on the USB's EFI (`EFI/OC/config.plist`) and decides:

| What it finds | What it does |
| :--- | :--- |
| No OpenCore, or a config OCLP didn't build | **Stops.** Run *Build and Install OpenCore* in OCLP first. |
| OCLP built it **spoofed** as another model | **Leaves it alone.** OCLP already set DataHub for the spoofed model. |
| Model, board ID and `UpdateDataHub` already set correctly | **Changes nothing** (`DataHub: OK`). |
| Model or board ID **empty**, or `UpdateDataHub` off | **Writes only what's missing:** the model OCLP built for, that model's board ID from OCLP's own model table ([`oclp_models.json`](oclp_models.json)), and `UpdateDataHub = true`. The config is backed up first. |
| A **different** value is already there | **Stops without overwriting**, so you can check it. |

**Why it can be missing:** OCLP fills in the DataHub board ID itself to prevent this boot loop, but only on Ivy Bridge and older Macs (roughly 2012 and earlier), or when you build with SMBIOS spoofing. A newer Mac built as itself gets both values empty. The script fills in the Mac's own real values, never a different model, so it's safe on Macs that would have booted without them.

If you rebuild OpenCore in OCLP later, run the script again. Use `--packages-only` to skip the DataHub step.

**Why this happens, with logs and source references:** [docs/OCLP-RC-ASSETS-BUG.md](docs/OCLP-RC-ASSETS-BUG.md). In short, OCLP looks for a GitHub release named `3.0.0` that doesn't exist during the RC phase. Its fallback saves a nightly.link 404 page as the package, and the step that copies the package and the KDK then quits silently.

| Situation | What to do |
| :--- | :--- |
| `Library/Packages` on the USB is missing or empty | Run Autopatch Rescue. |
| Boot loops on "failed to obtain model information" | Run Autopatch Rescue to fill in the DataHub values, or `--check` to see them. |
| You use a final OCLP release | The package download works on final releases. Run `--check` to see whether anything else is missing. |
| After the final 3.0.0 is published | Update OCLP first. An RC app would then download the final release's assets, which don't match it. |

## Installing on the target Mac

1. Plug the USB into the Mac you built it for, hold **Option** at power-on and choose **EFI Boot** (the USB's), then **Install macOS Tahoe**.
2. **Erase the target drive first:** open **Disk Utility** from the installer, erase the internal drive (APFS; GUID Partition Map if you erase the whole disk), then quit Disk Utility and choose **Install macOS Tahoe** onto it. This deletes everything on it, so back up first.
3. At **every restart**, hold Option and choose the USB's **EFI Boot** again: the **macOS Installer** entry while installing, then **Macintosh HD** once it's finished.
4. Near the end, the installer runs the two packages: OCLP installs itself, root patches, and restarts once more. Afterwards, OCLP's *Post-Install Root Patch* screen should show today's date.

Turn on **Verbose** in OCLP's build settings before *Build and Install OpenCore* (it's off by default), so a boot loop is easy to spot. If a Mac ever booted the USB while DataHub was blank and looped, leftover NVRAM can make it misbehave for a restart or two afterwards; an NVRAM reset (Option-Command-P-R) clears it.

## Booting without the USB

Autopatch Rescue only fixes the **USB**. To start without it, use OCLP on the installed Mac: **Build and Install OpenCore** onto the **internal drive's EFI**. OCLP builds that config the same way, so if DataHub was missing on the USB it will most likely be missing there too, and the internal config needs the same values. Autopatch Rescue doesn't do this yet.

## Further information

- [Why OCLP RC USBs miss AutoPkg-Assets.pkg and KDK.pkg](docs/OCLP-RC-ASSETS-BUG.md): logs, source references and the fix.
- [Testing](docs/TESTING.md): hardware results, the DataHub control test and the automated checks.

This is an unofficial tool. **OCLP and its contributors provide the actual patches and boot support.** This repo provides surrounding code and documentation, developed with AI assistance. See [NOTICE.md](NOTICE.md) for upstream sources and credits, and [LICENSE](LICENSE).
