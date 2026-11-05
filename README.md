# OCLP Tahoe Autopatch Rescue

![OCLP: 3.0.0 RC](https://img.shields.io/badge/OCLP-3.0.0--rc.5-f59e0b)
![macOS: Tahoe 26](https://img.shields.io/badge/macOS-Tahoe%2026-111827)
![Any OCLP Mac](https://img.shields.io/badge/model-any%20OCLP%20Mac-2563eb)

**Your OCLP Tahoe USB installs macOS, but nothing gets patched afterwards?** The OCLP 3.0.0 release candidates (RC1, RC2, RC3, RC5), the builds that add Tahoe support, create installer USBs **without `AutoPkg-Assets.pkg` and without `KDK.pkg`**, and still report success. After installing macOS, OCLP isn't installed and no root patches run, so Wi-Fi, graphics acceleration and audio may not work. It happens on every Mac model.

**Autopatch Rescue** checks the USB and adds exactly the two official files OCLP should have added, verified against GitHub's published SHA-256 digests.

```bash
git clone https://github.com/MrCee/oclp-tahoe-autopatch-rescue.git
cd oclp-tahoe-autopatch-rescue
python3 autopatch_rescue.py --usb "/Volumes/Install macOS Tahoe"
```

**The right order:** in OCLP, set **Settings → Target Model** to the Mac you'll install on, run **Create macOS Installer**, then **Build and Install OpenCore** onto the USB. *Then* run Autopatch Rescue on the same Mac, before you eject. It needs Python 3.9+, internet access and about 2.2 GB free on the USB. It reads the installer's macOS build and your installed OCLP release (for example `3.0.0-rc.5`). It skips files that are already correct, never edits a package (anything that doesn't match is deleted and downloaded again), and stops on anything it can't verify. Add `--check` to report without changing anything.

It also checks the OpenCore on the USB's EFI. If OCLP built it for the target Mac's own model and left the **DataHub model and board ID empty**, it fills in that model's real values from OCLP's own model table. Empty values caused the `Lilu: failed to obtain model information` boot loop on a MacBookPro11,3. It backs up `config.plist` first, never overwrites values that are already set, and leaves spoofed builds alone. Opening the EFI is why it asks for your Mac password; use `--packages-only` to skip this step. If you rebuild OpenCore in OCLP later, run it again.

**Why this happens, with logs and source references:** [docs/OCLP-RC-ASSETS-BUG.md](docs/OCLP-RC-ASSETS-BUG.md). In short, OCLP looks for a GitHub release named `3.0.0` that doesn't exist during the RC phase. Its fallback saves a nightly.link 404 page as the package, and the step that copies the package and the KDK then quits silently.

| Situation | What to do |
| :--- | :--- |
| `Library/Packages` on the USB is missing or empty | Run Autopatch Rescue. |
| Boot loops on `Lilu … failed to obtain model information` | Run Autopatch Rescue to fill in the DataHub values, or `--check` to see them. |
| Tested on hardware | MacBookPro11,3, OCLP 3.0.0-rc.5, Tahoe 26.7.2 (25G332), 2026-11-05: installed with no Lilu loop and working. |
| You use a final OCLP release (e.g. 2.5.1) | Not affected, but `--check` confirms it. |
| After the final 3.0.0 is published | Update OCLP first. An RC app would then download the final release's assets, which don't match it. |

---

## MacBookPro11,3 Tahoe guide (OCLP RC3, macOS 26.7.1)

![Model: MacBookPro11,3](https://img.shields.io/badge/model-MacBookPro11%2C3-2563eb)
![macOS: 26.7.1](https://img.shields.io/badge/macOS-26.7.1%20%2825G241%29-111827)
![OCLP: RC3](https://img.shields.io/badge/OCLP-3.0.0--rc.3-f59e0b)

**A four-step guide: create the USB, prepare it, install Tahoe, then set up booting without the USB.**

For the **mid-2014 15-inch MacBook Pro (MacBookPro11,3)** with Intel Iris Pro and NVIDIA GT 750M. This guide records the setup that worked with **Tahoe 26.7.1 / build 25G241 and OCLP 3.0.0 RC3**, and `prepare_usb.py` is pinned to exactly that. For OCLP RC5 or Tahoe 26.7.2, use [Autopatch Rescue](#oclp-tahoe-autopatch-rescue) above for the missing packages. **2026-11-05:** a USB made with OCLP RC5 for Tahoe 26.7.2 (25G332), then completed with Autopatch Rescue, installed Tahoe on this MacBookPro11,3 with **no Lilu loop**, and the owner reports it works. No step from this older guide was needed for the install. [Details](docs/TESTING.md#2026-11-05-oclp-rc5--tahoe-2672-with-autopatch-rescue).

> [!IMPORTANT]
> **Step 4 is required to boot without the USB in this workflow.**
> Install OpenCore onto the internal drive, then run the finishing tool **on the MacBook before rebooting**. Preparing the USB alone leaves this setup dependent on USB OpenCore.
>
> **Already have a working Tahoe desktop through the USB? Start at [step 4](#4-finish-opencore-on-the-internal-drive). Keep your installed system; you do not need to erase it again for this step.**

### Process overview

| Step | Where | What you do | Ready to continue when… |
| :--- | :--- | :--- | :--- |
| **[1. Create the USB](#1-create-the-oclp-usb)** | Working Mac | Use OCLP RC3 to create the installer and install USB OpenCore for 11,3. | The USB contains the Tahoe installer and OpenCore. |
| **[2. Prepare the USB](#2-prepare-the-usb)** | Working Mac | Run this repo’s preparation command. | It prints **PASS**; packages, EFI fixes and the finishing tool are ready. |
| **[3. Install Tahoe](#3-install-tahoe-on-the-macbook)** | MacBook Pro | Boot through USB EFI, install Tahoe and complete setup/root patching. | The desktop works while booted through USB OpenCore. |
| **[4. Finish internal OpenCore](#4-finish-opencore-on-the-internal-drive)** | **MacBook Pro** | Install internal OpenCore, then run the finishing tool from the USB. | The desktop works after a restart **with the USB disconnected**. |

**Reported working result:** on 17 October 2026, the owner confirmed completed setup and booting without the USB after the internal finishing step. This is one MacBookPro11,3 result. The newer USB launcher/automatic tools installation has fixture coverage and still needs a fresh hardware test. [Validation details](docs/TESTING.md).

### Before you start

- A working Mac: the MacBook itself or another Mac, such as an iMac.
- **Git and Python 3.9+ on the preparation Mac**, Internet access for missing official packages, and approximately **8 GiB free host storage**. Extra space may be needed for backups.
- An installer USB with enough space; **32 GB** was used for this workflow.
- OCLP **3.0.0 RC3** and the exact Tahoe installer/build above.

If Git/Python requests developer tools on the preparation Mac, run `xcode-select --install`, finish the installation window, then check `git --version` and `python3 --version`. A compiler is unnecessary for normal preparation when Python already works. The MacBook’s USB finishing launcher handles its own missing-tools setup in step 4.

### 1. Create the OCLP USB

**On the working Mac, in OCLP RC3:**

1. Set **Settings → Target Model → MacBookPro11,3**. Keep the other model defaults; Verbose Mode is optional.
2. Choose **Create macOS Installer** and write **Tahoe 26.7.1 / 25G241** to the USB. This erases the USB.
3. Choose **Build and Install OpenCore**, build it, then install onto **the USB’s EFI partition**.

Already created the installer? Select the correct target before building/installing USB OpenCore, then continue to step 2.

### 2. Prepare the USB

**On the working Mac, open Terminal:**

```bash
git clone https://github.com/MrCee/oclp-tahoe-autopatch-rescue.git
cd oclp-tahoe-autopatch-rescue
sudo python3 prepare_usb.py --usb "/Volumes/Install macOS Tahoe"
```

Already cloned this repo? Run `git pull --ff-only` inside its folder, then run the preparation command above. Replace the USB name if yours differs.

The command supplies the verified **RC3 assets and matching KDK packages**, applies the USB’s model/normal-boot fixes, and includes **`MBP113-Finish/finish-install.command`** for step 4. It saves backups and logs and shows download/copy progress. Valid existing packages are reused.

> [!IMPORTANT]
> **Wait for `PASS: supported USB preparation and report saving complete.`**
> If preparation stops, resolve the reported error and rerun. Rebuilding USB OpenCore can replace the fixes, so run preparation **after** the OCLP build/install.

Once it passes, safely eject the USB and its EFI volume. Package installation on the preparation Mac is unnecessary; the packages are staged for the Tahoe installer. [What the scripts change](docs/REFERENCE.md#what-the-scripts-change).

### 3. Install Tahoe on the MacBook

**On the MacBook Pro, with the prepared USB and charger connected:**

1. Start holding **Option**. Choose **USB EFI Boot**, then **Install macOS Tahoe**.
2. For the reported clean-install route, use Disk Utility to erase the intended **internal macOS target** as **APFS** (and **GUID Partition Map** if erasing the physical drive). **Erasing deletes its contents—back up first.** Keep the prepared USB intact. Quit Disk Utility and install Tahoe onto the internal target.
3. At each restart, boot through **USB EFI Boot**. Select the continuing **macOS Installer** entry while installation is underway, then **Macintosh HD** (or your internal volume’s name) when installation finishes. Avoid starting a new installation from the USB each time.
4. Complete user setup. In OCLP, check **Post-Install Root Patch**, apply required patches it reports, and reboot through USB EFI if needed.

**Checkpoint:** you have a usable Tahoe desktop through the USB. **Continue to step 4 before removing it.**

### 4. Finish OpenCore on the internal drive

**Required final step: boot without the USB.** Start in the MacBook’s installed Tahoe desktop, booted through the working USB EFI.

1. In **OCLP RC3**, confirm **Target Model → MacBookPro11,3**, choose **Build and Install OpenCore**, then install to the **internal physical drive containing Tahoe → its EFI partition**. Identify the drive by name, capacity and internal status; do not assume a disk number.
2. **Postpone OCLP’s reboot prompt.** Open **`MBP113-Finish` on the USB** and double-click **`finish-install.command`**. Alternatively, run:

   ```bash
   /bin/bash "/Volumes/Install macOS Tahoe/MBP113-Finish/finish-install.command"
   ```

   Replace the USB name if needed and enter the MacBook administrator password when asked. Keep the USB connected and writable until the helper finishes.
3. Require **`PASS: internal EFI configuration verified`**. Then shut down, disconnect the USB, start holding **Option**, and select **internal EFI Boot → Macintosh HD**.
4. Once that works, hold **Control** while selecting the internal EFI entry in Apple’s Option picker to make it the default. Test an ordinary restart **with the USB still disconnected**.

**Success:** the desktop loads without the USB. Keep the USB as a fallback.

The finishing tool runs when you open it; normal preparation installs no USB-mount or login watcher. It reuses **Python 3.9+** when available. If Python is missing, it discovers and installs Apple’s offered stable **Command Line Tools** package automatically, then checks Python again. **No Git or second clone is needed on the MacBook.** Setup and EFI backup/report files stay on the USB. [Tools setup, exact EFI changes and logs](docs/REFERENCE.md).

> [!IMPORTANT]
> **Repeat the finishing step after rebuilding internal OpenCore.**
> A fresh OCLP build can replace the model fixes that enabled booting. Post-install root patching and internal OpenCore installation are separate operations.

**If boot fails:** reconnect the USB and boot **USB EFI Boot → Macintosh HD**. Keep the error and logs, then check the [troubleshooting reference](docs/REFERENCE.md#if-something-stops). Keep the installed OS while resolving the boot configuration.

### Checks and logs

Audit a prepared USB without changing its files or permissions:

```bash
sudo python3 prepare_usb.py --usb "/Volumes/Install macOS Tahoe" --check
```

An unmounted EFI may be mounted read-only. See the [reference](docs/REFERENCE.md) for log locations, backups, manual packages, existing clones and older USBs.

### Further information

- [Why OCLP RC USBs miss AutoPkg-Assets.pkg and KDK.pkg](docs/OCLP-RC-ASSETS-BUG.md): logs, source references and the fix.
- [Technical reference and troubleshooting](docs/REFERENCE.md) — exact settings, tools setup, logs and advanced options.
- [Validation and limits](docs/TESTING.md) — owner-reported result, automated checks and remaining tests.
- [Troubleshooting history](docs/CASE-STUDY.md) — the observations behind this workflow.
- [Experimental Recovery fallback](docs/RECOVERY.md) — optional; outside the normal route above.

This is an unofficial, model-specific preparation workflow. **OCLP and its contributors provide the actual patches and boot support.** This repo provides surrounding preparation code and documentation, developed with AI assistance. See [upstream sources and credits](docs/REFERENCE.md#sources-and-credits), [NOTICE.md](NOTICE.md) and [LICENSE](LICENSE).
