"""Bundle the model-aware internal EFI finisher on an installer USB."""
import hashlib
import json
import os
from pathlib import Path
import tempfile

BASE = Path(__file__).resolve().parent
FOLDER = "OCLP-Finish"
LAUNCHER = "finish-install.command"
GUIDE = '''Finish internal OpenCore DataHub / macOS Tahoe 26

Audit the Mac FIRST. Do not rebuild OpenCore before checking its existing
internal configuration. The working USB's EFI and the internal SSD's EFI are
separate configurations: correcting one does not correct the other.

1. Boot the installed Tahoe desktop through the working USB's EFI Boot.
2. Inspect the internal configuration without changing it. In Terminal run:
   /bin/bash "/Volumes/Install macOS Tahoe/OCLP-Finish/finish-install.command" --check
   Replace the USB volume name if needed. Administrator access may be requested
   to open the internal EFI read-only. --check never installs tools or creates
   setup logs. If Python 3.9+ is missing, it stops; ask Codex to complete the
   read-only inspection using available tools before installing anything.
3. Read the result before making changes:
   - If internal OpenCore is absent, use OCLP to build OpenCore for this Mac
     onto the INTERNAL disk's EFI. Do not reboot yet. Check again.
   - If OpenCore exists and only the three DataHub settings are missing, run
     the normal finishing command below after reviewing the audit.
   - If the values are already correct, no DataHub edit is needed. Investigate
     the actual boot path and error before rebuilding or applying root patches.
   - If the model, board or storage conflicts, stop and review the finding.

Only when the audit establishes that a correction is needed, double-click
finish-install.command, or run:
   /bin/bash "/Volumes/Install macOS Tahoe/OCLP-Finish/finish-install.command"
Enter the Mac's administrator password when asked. The helper detects and
shows the installed OpenCore build target and the running Mac, then asks you
to use the matching target or stop. Confirm only if this is the right Mac.
To change the target, stop and rebuild/install the complete OpenCore build
through OCLP for the intended Mac, then run the audit again. Changing three
DataHub fields cannot retarget model-specific drivers, patches or USB maps.
There is no arbitrary model override. --yes skips the confirmation question,
but it does not bypass the model, disk or configuration checks.

Require PASS: internal EFI configuration verified. Then, when ready to test,
shut down, remove the USB, hold Option and select internal EFI Boot followed
by the installed Tahoe disk. Test an ordinary restart too. Keep the working
USB for recovery.

The finisher changes only these three DataHub settings in the existing internal
OpenCore configuration: SystemProductName, BoardProduct and UpdateDataHub.
The matching model and board ID come from the bundled OCLP model table. The
manifest verifies bundle integrity; it does not choose or prove the Mac model.
The helper reads the existing internal OCLP build target and checks it against
the running Mac. Unknown, inconsistent, conflicting or spoofed targets stop
for review. The tool does not use the USB's target as the internal target.
It backs up the configuration and reads the result back. It does not install
OpenCore, change root patches, install the KDK, erase a disk or restart the Mac.
Run it again after rebuilding internal OpenCore. A PASS verifies configuration;
successful booting without the USB still needs a separate test.

The generic path is covered by fixture tests. Hardware success has been
reported on MacBookPro11,3 only; other models have not been hardware-tested.
An existing MBP113-Finish folder is historical and is left untouched. Use this
OCLP-Finish folder for the current model-aware tool.

The launcher reuses working Python 3.9 or newer. If none is available, normal
mode installs only the newest stable compatible Apple Command Line Tools
package offered by softwareupdate. Internet is needed for that download.
It never selects a macOS upgrade. No Git clone or compiler is otherwise needed.
Setup output is saved under build/bootstrap/ in this folder. The configuration
backup is saved beside the internal EFI config; retain the paths it prints.
Normal mode proceeds to the DataHub correction after prerequisites are ready;
do not use it merely to install Python during the initial read-only audit.

HANDOVER TO CODEX ON THE TARGET MAC (copy and paste this prompt)

Read the READ-ME-FIRST.txt beside finish-install.command on the connected USB.
This is a read-only audit first. Check the actual Mac model, running macOS
version and exact build, and installed OCLP release tag. The app's displayed
3.0.0 alone does not identify its release candidate.
Identify the INTERNAL EFI belonging to the currently running installed APFS
system; open it read-only and inspect its existing EFI/OC/config.plist before
any rebuild. Read its OCLP-Model and #Revision/Original-Model and compare them
with the running Mac. Distinguish the hardware/reported model, the installed
build target and any SMBIOS spoof. Live NVRAM can describe the USB currently
supplying the boot; read the internal build target from its own config file.
Compare it with the USB's EFI/OC/config.plist, reading the USB without changing
it. Report these actual values from each separately, and compare them with the
matching model and board ID in the bundled oclp_models.json:
PlatformInfo/DataHub/SystemProductName
PlatformInfo/DataHub/BoardProduct
PlatformInfo/UpdateDataHub
Check /Library/Developer/KDKs for a KDK matching the RUNNING macOS build, and
read the OCLP root-patch record if available. Distinguish a KDK package merely
present on the USB from the KDK actually installed on this Mac, and
configuration verification from a successful boot without USB. Report the
findings and proposed next step before any OpenCore rebuild, configuration
edit, package/tools installation, root patch or reboot. Never edit the working
USB during this audit. Do not retarget the build merely by changing DataHub;
changing the Mac target requires a complete OCLP build/install for that Mac.
Follow this Mac's local AGENTS.md instructions.

END HANDOVER PROMPT

If a USB-free boot fails, reconnect the unchanged working USB and boot through
its EFI Boot into the installed Tahoe desktop. Do not erase the installation
to fix the internal EFI handover.

This folder is a snapshot of the finishing tools, not an auto-updating copy.
Guide: https://github.com/MrCee/oclp-tahoe-autopatch-rescue
'''


def safe(root, relative):
    """Return a managed path without following a symlink inside the folder."""
    root = Path(root)
    relative = Path(relative)
    if relative.is_absolute() or ".." in relative.parts or root.is_symlink():
        raise ValueError("Unsafe finishing-tool path.")
    path = root
    for part in relative.parts:
        path /= part
        if path.is_symlink():
            raise ValueError("Refusing a symlinked finishing-tool path: " + str(path))
    return path


def contents():
    files = {
        "finish_install.py": (BASE / "finish_install.py").read_bytes(),
        "oclp_models.json": (BASE / "oclp_models.json").read_bytes(),
        LAUNCHER: (BASE / "kit" / LAUNCHER).read_bytes(),
        "READ-ME-FIRST.txt": GUIDE.encode(),
    }
    manifest = {"format": 3, "macos_major": 26,
                "sha256": {name: hashlib.sha256(data).hexdigest() for name, data in files.items()}}
    files["manifest.json"] = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode()
    return files


def verify(usb, check_modes=True):
    folder = safe(Path(usb), FOLDER)
    if not folder.is_dir():
        raise ValueError("Finishing tools are missing: " + FOLDER)
    if check_modes and folder.stat().st_mode & 0o777 != 0o755:
        raise ValueError("Unexpected permissions at " + FOLDER)
    for name, expected in contents().items():
        path = safe(folder, name)
        if not path.is_file() or path.read_bytes() != expected:
            raise ValueError("Finishing tools are missing or outdated: " + name + "; rerun USB preparation.")
        mode = 0o755 if name == LAUNCHER else 0o644
        if check_modes and path.stat().st_mode & 0o777 != mode:
            raise ValueError("Unexpected finishing-tool permissions: " + name)


def install(usb, backup_dir):
    """Install only managed files; preserve logs and back up changed old files."""
    usb = Path(usb)
    backup_dir = Path(backup_dir).absolute()
    for component in (backup_dir, *backup_dir.parents):
        if component.is_symlink():
            raise ValueError("Refusing a symlinked finishing-tool backup directory.")
    usb_real = usb.resolve()
    if backup_dir == usb_real or usb_real in backup_dir.parents:
        raise ValueError("Finishing-tool replacement backups must be outside the USB.")
    folder = safe(usb, FOLDER)
    files = contents()
    if folder.exists() and not folder.is_dir():
        raise ValueError("Unexpected finishing-tool destination: " + str(folder))
    changed = []
    # Preflight every managed destination before making directories or backups.
    for name, data in files.items():
        path = safe(folder, name)
        if path.exists() and not path.is_file():
            raise ValueError("Unexpected finishing-tool destination: " + str(path))
        if not path.exists() or path.read_bytes() != data:
            changed.append((name, data))
    for name, _ in changed:
        old = folder / name
        if old.exists():
            backup_dir.mkdir(parents=True, exist_ok=True)
            with (backup_dir / name).open("xb") as out:
                out.write(old.read_bytes())
                out.flush()
                os.fsync(out.fileno())
    folder.mkdir(exist_ok=True)
    folder.chmod(0o755)
    # A partial update cannot pass launcher verification: publish manifest last.
    for name, data in sorted(changed, key=lambda item: item[0] == "manifest.json"):
        fd, temporary = tempfile.mkstemp(prefix=".finish-", dir=str(folder))
        try:
            with os.fdopen(fd, "wb") as out:
                out.write(data)
                out.flush()
                os.fsync(out.fileno())
            os.chmod(temporary, 0o755 if name == LAUNCHER else 0o644)
            os.replace(temporary, folder / name)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
    for name in files:
        (folder / name).chmod(0o755 if name == LAUNCHER else 0o644)
    verify(usb)
    return {"folder": FOLDER, "files": sorted(files), "bytes": sum(map(len, files.values())),
            "changed_files": [name for name, _ in changed]}
