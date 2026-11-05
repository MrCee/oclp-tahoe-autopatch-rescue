# Why OCLP release-candidate USBs are missing AutoPkg-Assets.pkg and KDK.pkg

**Short version:** in every OCLP **3.0.0 release candidate** published so far (RC1, RC2, RC3 and RC5; there is no RC4 release), *Create macOS Installer* looks for the automatic-patching package under a GitHub release called **`3.0.0`**. That release does not exist yet; the real ones are tagged `3.0.0-rc.1`, `-rc.2`, `-rc.3` and `-rc.5`. OCLP's fallback download then saves a **nightly.link "404 Not Found" web page** as the package. Unpacking that fails without being checked, so OCLP quietly skips the step that copies **`AutoPkg-Assets.pkg`** to the USB, and with it the step that adds **`KDK.pkg`**. It still reports the installer as created successfully.

The result is a USB that installs macOS but **does not install OCLP or root patch afterwards**. The model doesn't matter. [`autopatch_rescue.py`](../autopatch_rescue.py) adds exactly the two files OCLP should have added.

This was observed on 2026-11-05 with the official, notarised **OCLP 3.0.0-rc.5** app, creating a **macOS Tahoe 26.7.2 (25G332)** installer on an iMac18,2 for a MacBookPro11,3. The same code path exists in RC3, and the earlier RC3 USBs needed the same packages supplied by hand (see the [case study](CASE-STUDY.md#4-logs-identified-a-missing-matching-kdk)).

## What a complete OCLP USB contains

When *Create macOS Installer* works, OCLP puts these files in the installer volume's `Library/Packages/` folder:

| File | Where it comes from | What it does |
| :--- | :--- | :--- |
| `AutoPkg-Assets.pkg` | The OCLP GitHub release matching the app | After macOS installs, the installer runs it: it installs the OCLP app and helper, runs `--patch_sys_vol` (root patching), then restarts. Works together with `AutoPkgInstaller.kext` in the USB's OpenCore. |
| `KDK.pkg` | Apple's Kernel Debug Kit for the installer's exact build, via [dortania/KdkSupportPkg](https://github.com/dortania/KdkSupportPkg/releases) | Installed alongside, so that patches which rebuild the kernel collection can run on first boot **without internet**. |
| `MetallibSupportPkg.pkg` | Only for macOS Sequoia 15 | Not used on Tahoe. |

## Step by step: what goes wrong

Line references are to the [3.0.0-rc.5 tag](https://github.com/dortania/OpenCore-Legacy-Patcher/tree/3.0.0-rc.5).

### 1. The download address uses the version number, not the release tag

[`constants.py` L16 and L26](https://github.com/dortania/OpenCore-Legacy-Patcher/blob/3.0.0-rc.5/opencore_legacy_patcher/constants.py#L16-L27):

```python
self.patcher_version:   str = "3.0.0"
self.installer_pkg_url: str = f"{self.repo_link}/releases/download/{self.patcher_version}/AutoPkg-Assets.pkg"
```

Every RC build has `patcher_version = "3.0.0"`. That's also why the OCLP window only ever shows "3.0.0", whichever RC is installed. The resulting address:

| URL | Result |
| :--- | :--- |
| `…/releases/download/3.0.0/AutoPkg-Assets.pkg` | **404 Not Found**: there is no `3.0.0` release yet |
| `…/releases/download/3.0.0-rc.5/AutoPkg-Assets.pkg` | 302 → the real 967 MB package |

### 2. The fallback goes to a nightly build that doesn't exist

[`gui_macos_installer_flash.py` L412–444](https://github.com/dortania/OpenCore-Legacy-Patcher/blob/3.0.0-rc.5/opencore_legacy_patcher/wx_gui/gui_macos_installer_flash.py#L412-L444) checks the link, logs **"Stock Install.pkg is missing on Github, falling back to Nightly"**, and downloads from nightly.link instead. The release build used this address:

```text
http://nightly.link/dortania/OpenCore-Legacy-Patcher/workflows/build-app-wxpython/refs/tags/3.0.0-rc.5/AutoPkg-Assets.pkg.zip
```

nightly.link answers with an HTML error page, which OCLP saves as the zip. This is the file it left in its temporary `payloads/` folder (495 bytes):

```html
<title>nightly.link</title>
<h1>Error 404 &ndash; Not Found</h1>
<p>/dortania/OpenCore-Legacy-Patcher/workflows/build-app-wxpython/refs/tags/3.0.0-rc.5/AutoPkg-Assets.pkg.zip</p>
```

The OCLP log records it as a successful download:

```text
Error determining file size http://nightly.link/…/refs/tags/3.0.0-rc.5/AutoPkg-Assets.pkg.zip: Content-Length missing from headers
Assuming file size is 0
Download complete: AutoPkg-Assets.pkg.zip
- Downloaded size: 495.0 B
```

### 3. The unzip failure is ignored

L444 runs `ditto -x -k` on the "zip" without checking the result, so no `AutoPkg-Assets.pkg` is produced.

### 4. The package step quits silently, and the KDK step goes with it

[`_install_installer_pkg` L447–468](https://github.com/dortania/OpenCore-Legacy-Patcher/blob/3.0.0-rc.5/opencore_legacy_patcher/wx_gui/gui_macos_installer_flash.py#L447-L468) starts with:

```python
if not Path(self.constants.installer_pkg_path).exists():
    return
```

It returns without logging or showing anything. The KDK and Metallib downloads are **inside the same function, after the package copy** (L466–468: `# Chainload KDK and Metallib`), so they never run. **That's why `KDK.pkg` is missing too:** the debug kit was never attempted, not separately rejected.

### 5. The success message checks something else

The log then shows **"Installer pkg validated"**, and OCLP offers to install OpenCore with "Installer created successfully". [`_validate_installer_pkg` L593–622](https://github.com/dortania/OpenCore-Legacy-Patcher/blob/3.0.0-rc.5/opencore_legacy_patcher/wx_gui/gui_macos_installer_flash.py#L593-L622) only runs `hdiutil verify` on Apple's `SharedSupport.dmg`. It doesn't look at `Library/Packages`, so the missing OCLP packages aren't reported.

## Which OCLP builds are affected

- **Affected:** any OCLP build whose `patcher_version` has no GitHub release with exactly that name. That's every 3.0.0 release candidate (RC1, RC2, RC3, RC5), because all of them report `3.0.0`.
- **Not affected:** final releases. Their version and tag are the same (for example `2.5.1`, the current latest release), so step 1 finds the package and nothing else goes wrong.
- **Caution for later:** once a final `3.0.0` release is published, an **RC app** will find *that* package and copy the **3.0.0 final assets** onto the USB, which don't match the RC app you're running. Update OCLP to the final release before creating a USB at that point.
- **In practice this means Tahoe.** The 3.0.0 RCs are the builds that add macOS Tahoe 26 support, so Tahoe installers are where people hit it. The code path itself would affect any Big Sur or newer installer made with an RC.
- **Doesn't depend on the target Mac.** The download and copy happen before any model-specific logic. Every model built from an affected OCLP gets a USB without automatic patching.

## Do I need the KDK?

If your USB was hit by this bug, add it. That's what OCLP itself would have done for every Big Sur or newer installer, whatever the model. Without it, first-boot root patching has to download the debug kit, and Wi-Fi often doesn't work until after patching.

On Tahoe it's strictly required for any Mac without a T2 chip. That's because of the **Modern Audio** patch: [`modern_audio.py`](https://github.com/dortania/OpenCore-Legacy-Patcher/blob/3.0.0-rc.5/opencore_legacy_patcher/sys_patch/patchsets/hardware/misc/modern_audio.py) applies when `SecureBootModel` is `None` and returns `requires_kernel_debug_kit → xnu >= tahoe`. For example:

- **MacBookPro11,3** (`SecureBootModel: None`) gets Modern Audio, so it needs the KDK.
- **iMac18,2** RC5 patch record from the same day: Modern Wireless + Modern Audio, *Kernel Debug Kit Used: KDK_26.7.1_25G241.kdk*.

`MetallibSupportPkg` is **not** needed on Tahoe. The Haswell/Kepler predicates require it only for `sequoia <= xnu < tahoe`.

## Worked example: why a MacBookPro11,3 needs both

Every OCLP Mac needs root patches after a fresh install. The question for any model is **which patches, and whether they can run on first boot**. Here is how it works out for a mid-2014 15-inch MacBook Pro (Intel Iris Pro + NVIDIA GT 750M) on Tahoe, using the RC5 patch definitions:

| Patch set | Why it applies to this Mac | Native until | Needs KDK? |
| :--- | :--- | :--- | :--- |
| Modern Wireless | Broadcom `AirportBrcmNIC` Wi-Fi ([`modern_wireless.py`](https://github.com/dortania/OpenCore-Legacy-Patcher/blob/3.0.0-rc.5/opencore_legacy_patcher/sys_patch/patchsets/hardware/networking/modern_wireless.py)) | Ventura | No |
| Intel Haswell graphics | Iris Pro 5200 ([`intel_haswell.py`](https://github.com/dortania/OpenCore-Legacy-Patcher/blob/3.0.0-rc.5/opencore_legacy_patcher/sys_patch/patchsets/hardware/graphics/intel_haswell.py)) | Monterey | No |
| NVIDIA Kepler graphics | GT 750M ([`nvidia_kepler.py`](https://github.com/dortania/OpenCore-Legacy-Patcher/blob/3.0.0-rc.5/opencore_legacy_patcher/sys_patch/patchsets/hardware/graphics/nvidia_kepler.py)) | Big Sur / early Monterey | No |
| Modern Audio | No T2 chip (`SecureBootModel: None`) | Sequoia | **Yes, on Tahoe** |

Without the two packages, the chain breaks:

1. **No `AutoPkg-Assets.pkg`**: after the install, OCLP isn't on the Mac and no patching runs. The desktop has no Wi-Fi, no graphics acceleration and no audio.
2. **Patching by hand needs OCLP and the KDK**: you'd have to get the OCLP installer onto the Mac, and root patching then has to download the 25G332 KDK for Modern Audio.
3. **But there's no network**: Wi-Fi is one of the things waiting to be patched, and this MacBook has no Ethernet port. Without a Thunderbolt Ethernet adapter or a USB Wi-Fi dongle, it can't download anything.

With both packages on the USB, the installer installs OCLP and the KDK, root patches everything above on first boot **offline**, and restarts into a working system. The earlier RC3 install on this machine hit exactly this: the patch record showed Modern Wireless only, with the graphics patches missing and a failed KDK lookup ([case study](CASE-STUDY.md#4-logs-identified-a-missing-matching-kdk)).

**For other Macs:** the missing-package bug is the same, but the patch list isn't. A Mac with built-in Ethernet can recover by patching manually; a Wi-Fi-only Mac usually can't. The KDK matters whenever any patch set returns `requires_kernel_debug_kit` for your macOS version. On Tahoe that includes Modern Audio for every Mac without a T2. Adding both packages, as OCLP intends, covers all models.

## How to tell whether your USB is affected

1. Look in **`/Volumes/Install macOS …/Library/Packages/`**. It should contain `AutoPkg-Assets.pkg` and `KDK.pkg`. If the folder doesn't exist, your USB was hit.
2. Or look in the OCLP log (`~/Library/Logs/Dortania/`) for `Stock Install.pkg is missing on Github` and `Downloaded size: 495.0 B`.
3. Or run `python3 autopatch_rescue.py --usb "/Volumes/Install macOS Tahoe" --check`.

## The fix

```bash
python3 autopatch_rescue.py --usb "/Volumes/Install macOS Tahoe"
```

It does what OCLP's code meant to do, using the correct release tag:

1. Reads the installer's macOS build from the USB and the OCLP release tag from the installed app (`Info.plist → Github → Branch`, e.g. `refs/tags/3.0.0-rc.5`).
2. Downloads `AutoPkg-Assets.pkg` from **that tag's** release and the `Kernel_Debug_Kit_<version>_build_<build>.dmg` from KdkSupportPkg. Each one is checked against the SHA-256 digest GitHub publishes. An HTML error page or a truncated file is rejected, not copied.
3. Copies the package, and the Apple-signed `KernelDebugKit.pkg` from inside the disk image as `KDK.pkg`, into `Library/Packages/`, which is the same place and name OCLP uses. It verifies each copy before putting it in place.
4. Never edits a package. Any package on the USB, or in its download cache, that doesn't match is **deleted and downloaded again**. Leftover partial copies are deleted too.
5. Checks the OpenCore on the USB's EFI (needs `sudo`). If OCLP built it for the target Mac's own model (`OCLP-Model`, no SMBIOS spoof) and left `PlatformInfo/DataHub/SystemProductName` and `BoardProduct` empty with `UpdateDataHub` off, it sets them to that model and its board ID from OCLP's own table ([`oclp_board_ids.json`](../oclp_board_ids.json), from RC5's `smbios_data.py`). It backs up the config first, and it won't overwrite a value someone else set. This is a separate issue from the missing packages: on the MacBookPro11,3 the empty values caused the Lilu boot loop described in the [case study](CASE-STUDY.md#2-explicit-datahub-values-cleared-the-loop). OCLP RC5 still leaves them empty.
6. Leaves files that are already correct alone, and keeps a small `.autopatch-rescue.json` record at the top of the USB so a later `--check` can verify `KDK.pkg`.

Nothing is installed on the Mac you run it from, and no disk is erased. Build and install OpenCore onto the USB's EFI in OCLP as usual; the script doesn't touch the EFI.

## Upstream

The underlying fix belongs in OCLP: build the release URL from the build's tag (not `patcher_version`), check the download and unzip results, and stop with a clear error instead of returning silently. A local fork branch (`codex/installer-assets-release-validation`, *"installer: select tagged assets and report preparation failures"*) prototypes this, but it hasn't been submitted upstream.
