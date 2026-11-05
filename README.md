# OCLP Tahoe Autopatch Rescue

![OCLP: 3.0.0 RC](https://img.shields.io/badge/OCLP-3.0.0--rc.5-f59e0b)
![macOS: Tahoe 26](https://img.shields.io/badge/macOS-Tahoe%2026-111827)
![Any OCLP Mac](https://img.shields.io/badge/model-any%20OCLP%20Mac-2563eb)

**If you've landed here, OCLP's normal process didn't work for you.** You built a Tahoe installer USB with an OCLP 3.0.0 release candidate, installed macOS, and either it got stuck in a boot loop or nothing was patched afterwards, so Wi-Fi, graphics acceleration or audio don't work.

**Autopatch Rescue is an alternative way to finish the USB installer.** Run it on the USB, then install again. It checks the USB and adds what the normal process should have put there:

- **`AutoPkg-Assets.pkg` and `KDK.pkg`.** OCLP 3.0.0 release candidates build USBs without them and still report success, so OCLP never installs itself or patches after the install. Seen with RC5; RC1, RC2 and RC3 contain the same download code. The assets package and the KDK disk image are downloaded from the official GitHub releases and checked against GitHub's published SHA-256 digests, and the `KDK.pkg` taken from the image must be Apple-signed.
- **The OpenCore DataHub model and board ID**, only if they're missing. On the MacBookPro11,3, empty values cause an immediate "failed to obtain model information" boot loop.

How much this matters depends on your Mac. The packages are missing from every RC-built USB, but the DataHub fix has only been proven on the MacBookPro11,3.

**Before you start:** plan on a **clean install**. Back up, then in the installer's Disk Utility **erase the target internal drive** (APFS, GUID Partition Map) before installing Tahoe from the adjusted USB. That's how this was tested.

```bash
git clone https://github.com/MrCee/oclp-tahoe-autopatch-rescue.git
cd oclp-tahoe-autopatch-rescue
python3 autopatch_rescue.py --usb "/Volumes/Install macOS Tahoe"
```

**The right order:** in OCLP, set **Settings → Target Model** to the Mac you'll install on, run **Create macOS Installer**, then **Build and Install OpenCore** onto the USB. *Then* run Autopatch Rescue on the same Mac, before you eject. It needs Python 3.9+, internet access and about 2.2 GB free on the USB. It reads the installer's macOS build and your installed OCLP release (for example `3.0.0-rc.5`). It skips files that are already correct, never edits a package (anything that doesn't match is deleted and downloaded again), and stops on anything it can't verify. Add `--check` to report without changing anything.

It also checks the OpenCore on the USB's EFI each time it runs, and writes the **DataHub model and board ID only if they're missing**. If OCLP built it for the target Mac's own model and left them empty, it fills in that model's real values from OCLP's own model table. If they're already correct it changes nothing. On a MacBookPro11,3, empty values cause an immediate "failed to obtain model information" boot loop. That was **proven with RC5** by booting the same USB with DataHub left blank. It backs up `config.plist` first, never overwrites values that are already set, and leaves spoofed builds alone. Opening the EFI is why it asks for your Mac password; use `--packages-only` to skip this step. If you rebuild OpenCore in OCLP later, run it again.

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

Turn on **Verbose** in OCLP's build settings before *Build and Install OpenCore* (it's off by default), so a boot loop is easy to spot. If you ever boot the USB with the DataHub values blank and see "failed to obtain model information", leftover NVRAM can make the Mac misbehave for a restart or two afterwards; an NVRAM reset (Option-Command-P-R) clears it.

## Booting without the USB

Autopatch Rescue only fixes the **USB**. To start without it, use OCLP on the installed Mac: **Build and Install OpenCore** onto the **internal drive's EFI**. Expect OCLP to leave the DataHub values empty there too, since it uses the same build code. On Macs that need them (like the MacBookPro11,3), the internal config then needs the same three values. Autopatch Rescue doesn't do this yet.

## Tested

| Mac | OCLP | macOS | Result |
| :--- | :--- | :--- | :--- |
| MacBookPro11,3 (mid-2014 15-inch, Iris Pro + GT 750M) | 3.0.0-rc.5 | Tahoe 26.7.2 (25G332) | **Works** with Autopatch Rescue (both packages + DataHub): Tahoe installed with no boot loop and the owner reports it working. Control test with DataHub blank: immediate "failed to obtain model information" loop. [Details](docs/TESTING.md) |

## Further information

- [Why OCLP RC USBs miss AutoPkg-Assets.pkg and KDK.pkg](docs/OCLP-RC-ASSETS-BUG.md): logs, source references and the fix.
- [Validation and limits](docs/TESTING.md): hardware results and automated checks.

This is an unofficial tool. **OCLP and its contributors provide the actual patches and boot support.** This repo provides surrounding code and documentation, developed with AI assistance. See [NOTICE.md](NOTICE.md) for upstream sources and credits, and [LICENSE](LICENSE).
