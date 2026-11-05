"""Small, self-contained USB copy of the internal EFI finishing tools."""
import hashlib
import json
import os
from pathlib import Path
import tempfile

BASE = Path(__file__).resolve().parent
FOLDER = 'MBP113-Finish'
MODULES = ('finish_install.py', 'fix_efi.py', 'build_kit.py', 'prepare_usb.py', 'finish_bundle.py')
LAUNCHER = 'finish-install.command'
GUIDE = '''Finish the internal OpenCore setup on MacBookPro11,3

1. Boot the installed Tahoe desktop through the working USB EFI.
2. In OCLP RC3, Build and Install OpenCore for MacBookPro11,3 to the INTERNAL disk EFI.
3. Before rebooting, double-click finish-install.command in this folder, or run:
   /bin/bash "/Volumes/Install macOS Tahoe/MBP113-Finish/finish-install.command"
   Replace the USB volume name if it differs. Enter the MacBook administrator password when asked.
4. Require PASS: internal EFI configuration verified. Shut down, remove USB,
   then use Option -> internal EFI Boot -> Macintosh HD. Test an ordinary restart too.

The launcher reuses an existing Python 3.9+ and verifies the bundled files.
It does not need Git, another clone, or a compiler. If Python is unavailable,
it automatically discovers and installs the newest stable compatible Command Line
Tools package offered by Apple's softwareupdate, then checks Python again.
Internet is needed for that installation only. No other macOS update is selected.
The macOS python3 launcher alone may request tools; no separate Python download
is needed when Apple's installed tools already provide a suitable version.

Administrator access is requested once. Setup/download output is logged under
this folder's build/bootstrap/. If Apple offers no stable compatible tools or the
download fails, it stops without changing internal EFI and gives manual options.

Backups/reports are saved in this folder's build/internal-efi/<timestamp>/,
and a config backup is saved beside the internal EFI config before changes.
Keep the USB connected and writable until the script finishes.
If boot fails, reconnect this unchanged USB and boot USB EFI Boot -> Macintosh HD.
Do not erase a working Tahoe installation to fix this handover.
Rebuilding internal OpenCore later requires repeating the finishing step.

Guide and updates: https://github.com/MrCee/oclp-tahoe-autopatch-rescue
This bundle is a snapshot from USB preparation, not an automatically updating copy.
'''


def safe(root, relative):
    path = root
    for part in Path(relative).parts:
        if part in ('..', '/'):
            raise ValueError('Unsafe finishing-tool path.')
        path /= part
        if path.is_symlink():
            raise ValueError('Refusing a symlinked finishing-tool path: ' + str(path))
    return path


def contents():
    files = {name: (BASE / name).read_bytes() for name in MODULES}
    files[LAUNCHER] = (BASE / 'kit' / LAUNCHER).read_bytes()
    files['READ-ME-FIRST.txt'] = GUIDE.encode()
    manifest = {'format': 1, 'model': 'MacBookPro11,3', 'build': '25G241',
                'sha256': {name: hashlib.sha256(data).hexdigest() for name, data in files.items()}}
    files['manifest.json'] = (json.dumps(manifest, indent=2, sort_keys=True) + '\n').encode()
    return files


def verify(usb, check_modes=True):
    folder = safe(Path(usb), FOLDER)
    if check_modes and folder.stat().st_mode & 0o777 != 0o755:
        raise ValueError('Unexpected permissions at ' + FOLDER)
    for name, expected in contents().items():
        path = safe(folder, name)
        if not path.is_file() or path.read_bytes() != expected:
            raise ValueError('Finishing tools are missing or outdated: ' + name + '; rerun USB preparation.')
        mode = 0o755 if name == LAUNCHER else 0o644
        if check_modes and path.stat().st_mode & 0o777 != mode:
            raise ValueError('Unexpected finishing-tool permissions: ' + name)


def install(usb, backup_dir):
    usb = Path(usb)
    backup_dir = Path(backup_dir).resolve()
    if backup_dir == usb or usb in backup_dir.parents:
        raise ValueError('Finishing-tool replacement backups must be outside the USB.')
    folder = safe(usb, FOLDER)
    files = contents()
    changed = []
    # Validate every destination before touching any of the managed files.
    if folder.exists() and not folder.is_dir():
        raise ValueError('Unexpected finishing-tool destination: ' + str(folder))
    for name, data in files.items():
        path = safe(folder, name)
        if path.exists() and not path.is_file():
            raise ValueError('Unexpected finishing-tool destination: ' + str(path))
        if not path.exists() or path.read_bytes() != data:
            changed.append((name, data))
    for name, _ in changed:
        old = folder / name
        if old.exists():
            backup_dir.mkdir(parents=True, exist_ok=True)
            saved = backup_dir / name
            with saved.open('xb') as out:
                out.write(old.read_bytes())
    folder.mkdir(exist_ok=True)
    folder.chmod(0o755)
    # Manifest goes last so an interrupted update fails its launch-time check.
    for name, data in sorted(changed, key=lambda item: item[0] == 'manifest.json'):
        fd, temporary = tempfile.mkstemp(prefix='.finish-', dir=str(folder))
        try:
            with os.fdopen(fd, 'wb') as out:
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
    return {'folder': FOLDER, 'files': sorted(files), 'bytes': sum(map(len, files.values())),
            'changed_files': [name for name, _ in changed]}
