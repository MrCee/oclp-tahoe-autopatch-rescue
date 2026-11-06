#!/usr/bin/env python3
"""Preserve MacBookPro11,3 DataHub settings in the installed system's internal EFI.

Run from the installed Tahoe desktop after OCLP's Build and Install OpenCore.
This standalone helper never installs OpenCore, root patches, packages or updates.
"""
import argparse
import contextlib
import copy
import datetime
import json
import os
from pathlib import Path
import plistlib
import re
import subprocess
import sys
import tempfile

BASE = Path(__file__).resolve().parent
MODEL = "MacBookPro11,3"
BOARD = "Mac-2BD1B31983FE1663"
OCLP_GUID = "4D1FDA02-38C7-4A6A-9CC6-4BCCA8B30102"
PARTITION = re.compile(r"disk[0-9]+s[0-9]+")
WHOLE_DISK = re.compile(r"disk[0-9]+")


class FinishError(ValueError):
    pass


def output(command):
    return subprocess.check_output(command)


def disk_info(device):
    return plistlib.loads(output(["/usr/sbin/diskutil", "info", "-plist", str(device)]))


def validate_host():
    model = output(["/usr/sbin/sysctl", "-n", "hw.model"]).decode().strip()
    version = output(["/usr/bin/sw_vers", "-productVersion"]).decode().strip()
    build = output(["/usr/bin/sw_vers", "-buildVersion"]).decode().strip()
    kernel = output(["/usr/bin/uname", "-r"]).decode().strip()
    if model != MODEL or version.split(".")[0] != "26" or kernel.split(".")[0] != "25":
        raise FinishError("Run this on the MacBookPro11,3 installed macOS Tahoe desktop, "
                          "not the preparation Mac or Recovery. No EFI changed.")
    return {"model": model, "macos_version": version, "macos_build": build}


def safe_path(root, relative):
    """Reject absolute paths, traversal and symlinks in every managed path."""
    root = Path(root)
    if root.is_symlink():
        raise FinishError("Refusing a symlinked path: " + str(root))
    if not isinstance(relative, str) or not relative or "\\" in relative:
        raise FinishError("Invalid OpenCore file path.")
    parts = relative.split("/")
    if any(part in ("", ".", "..") for part in parts):
        raise FinishError("Refusing an absolute or traversing file path: " + relative)
    path = root
    for part in parts:
        path /= part
        if path.is_symlink():
            raise FinishError("Refusing a symlinked path: " + str(path))
    return path


def internal_efi():
    """Resolve a System volume or its boot snapshot to one internal GPT disk."""
    root = disk_info("/")
    if (root.get("Internal") is not True or root.get("FilesystemType") != "apfs"
            or root.get("MountPoint") != "/" or root.get("SystemImage") is True
            or not root.get("APFSVolumeGroupID")):
        raise FinishError("Expected the installed system on an internal APFS System volume; "
                          "Recovery, installer and external systems are not supported.")
    device = root.get("DeviceIdentifier", "")
    if root.get("APFSSnapshot") is True:
        if not re.fullmatch(r"disk[0-9]+s[0-9]+s[0-9]+", device):
            raise FinishError("Cannot identify the running APFS snapshot's System volume.")
        device = device.rsplit("s", 1)[0]
    if not PARTITION.fullmatch(device):
        raise FinishError("Cannot identify the running APFS System volume.")
    reference = root.get("APFSContainerReference", "")
    containers = plistlib.loads(output(["/usr/sbin/diskutil", "apfs", "list", "-plist"]))
    matches = [c for c in containers.get("Containers", [])
               if c.get("ContainerReference") == reference]
    if not WHOLE_DISK.fullmatch(reference) or len(matches) != 1:
        raise FinishError("Cannot uniquely identify the running system's APFS container.")
    container = matches[0]
    systems = [v for v in container.get("Volumes", [])
               if v.get("DeviceIdentifier") == device and v.get("Roles") == ["System"]]
    if len(systems) != 1:
        raise FinishError("The running volume is not an installed APFS System volume; "
                          "do not run this from Recovery or the installer.")
    stores = container.get("PhysicalStores", [])
    if len(stores) != 1:
        raise FinishError("Expected exactly one APFS physical store; multi-disk systems are refused.")
    store_id = stores[0].get("DeviceIdentifier", "")
    root_stores = root.get("APFSPhysicalStores")
    if root_stores is not None and [s.get("APFSPhysicalStore") for s in root_stores] != [store_id]:
        raise FinishError("The running system's APFS physical-store identities disagree.")
    if not PARTITION.fullmatch(store_id):
        raise FinishError("Cannot safely identify the running system's APFS physical store.")
    store = disk_info(store_id)
    parent = store.get("ParentWholeDisk", "")
    if (store.get("Internal") is not True or store.get("Content") != "Apple_APFS"
            or not store.get("DiskUUID") or not WHOLE_DISK.fullmatch(parent)):
        raise FinishError("The APFS physical store is not a verified internal disk partition.")
    whole = disk_info(parent)
    if (whole.get("Internal") is not True or whole.get("WholeDisk") is not True
            or whole.get("VirtualOrPhysical") != "Physical"
            or whole.get("Content") != "GUID_partition_scheme"):
        raise FinishError("Expected an internal physical disk using GUID Partition Map.")
    listing = plistlib.loads(output(["/usr/sbin/diskutil", "list", "-plist", parent]))
    disks = [d for d in listing.get("AllDisksAndPartitions", [])
             if d.get("DeviceIdentifier") == parent]
    if len(disks) != 1:
        raise FinishError("Cannot uniquely identify the internal physical disk's partitions.")
    candidates = []
    for part in disks[0].get("Partitions", []):
        if part.get("Content") != "EFI":
            continue
        partition = part.get("DeviceIdentifier", "")
        if not PARTITION.fullmatch(partition):
            raise FinishError("Invalid internal EFI partition identifier.")
        info = disk_info(partition)
        if (info.get("Content") == "EFI" and info.get("Internal") is True
                and info.get("ParentWholeDisk") == parent and info.get("DiskUUID")):
            candidates.append(info)
    if len(candidates) != 1:
        raise FinishError("Expected exactly one verified EFI on the running system's internal disk.")
    result = dict(candidates[0])
    result["SystemIdentity"] = {"system_volume": device,
                                "volume_group": root["APFSVolumeGroupID"],
                                "container": reference, "physical_store": store_id,
                                "physical_store_uuid": store["DiskUUID"]}
    return result


def same_efi(original, current, include_system=False):
    keys = ["DeviceIdentifier", "DiskUUID", "ParentWholeDisk", "Content", "Internal"]
    if include_system:
        keys.append("SystemIdentity")
    if any(original.get(key) != current.get(key) for key in keys):
        raise FinishError("Internal EFI or running system identity changed; stopping without a config write.")


@contextlib.contextmanager
def mounted_efi(info, check=False):
    device = info["DeviceIdentifier"]
    current = disk_info(device)
    same_efi(info, current)
    opened = False
    try:
        if not current.get("MountPoint"):
            command = ["/usr/sbin/diskutil", "mount"]
            if check:
                command.append("readOnly")
            subprocess.run(command + [device], check=True, capture_output=True)
            opened = True
            current = disk_info(device)
            same_efi(info, current)
        mount = current.get("MountPoint")
        if not mount or not os.path.ismount(mount):
            raise FinishError("The internal EFI did not mount.")
        if not check and current.get("WritableVolume") is False:
            raise FinishError("Internal EFI is read-only. Unmount that EFI normally, then rerun; "
                              "no force-unmount is attempted.")
        root = Path(mount)
        safe_path(root, "EFI/OC")
        yield root
    finally:
        if opened:
            # Only unmount the exact partition we opened; leave user mounts alone.
            same_efi(info, disk_info(device))
            subprocess.run(["/usr/sbin/diskutil", "unmount", device], check=True, capture_output=True)


def require_file(path):
    if not path.is_file() or path.stat().st_size == 0:
        raise FinishError("Missing or empty enabled OpenCore file: " + str(path))


def check_boot_files(mount, config):
    require_file(safe_path(mount, "EFI/OC/OpenCore.efi"))
    layouts = []
    for name, relative in (("Apple", "System/Library/CoreServices/boot.efi"),
                           ("UEFI", "EFI/BOOT/BOOTx64.efi")):
        path = safe_path(mount, relative)
        if path.is_file() and path.stat().st_size:
            layouts.append(name)
    if not layouts:
        raise FinishError("Internal OpenCore bootstrap is missing. Build and Install OpenCore "
                          "to the INTERNAL drive's EFI in OCLP first, then rerun before rebooting.")
    for section, key, folder in (("ACPI", "Add", "ACPI"), ("UEFI", "Drivers", "Drivers")):
        for entry in config.get(section, {}).get(key, []):
            if not isinstance(entry, dict):
                raise FinishError("Expected current OCLP " + section + " entries.")
            if entry.get("Enabled"):
                require_file(safe_path(safe_path(mount, "EFI/OC/" + folder), entry.get("Path", "")))
    for entry in config.get("Kernel", {}).get("Add", []):
        if not isinstance(entry, dict):
            raise FinishError("Expected current OCLP Kernel/Add entries.")
        if entry.get("Enabled"):
            bundle = safe_path(safe_path(mount, "EFI/OC/Kexts"), entry.get("BundlePath", ""))
            if not entry.get("PlistPath"):
                raise FinishError("An enabled OpenCore kext has no PlistPath.")
            for key in ("PlistPath", "ExecutablePath"):
                if entry.get(key):
                    require_file(safe_path(bundle, entry[key]))
    return " + ".join(layouts)


def corrected_config(original):
    config = copy.deepcopy(original)
    target = config.get("NVRAM", {}).get("Add", {}).get(OCLP_GUID, {}).get("OCLP-Model")
    revision = config.get("#Revision", {}).get("Original-Model", MODEL)
    if target != MODEL or revision != MODEL:
        raise FinishError("OCLP must already have been built for MacBookPro11,3 on the internal EFI.")
    platform = config.get("PlatformInfo")
    if not isinstance(platform, dict) or not isinstance(platform.get("DataHub"), dict):
        raise FinishError("Expected an existing OCLP PlatformInfo/DataHub section.")
    generic = platform.get("Generic", {}).get("SystemProductName", "")
    if platform.get("Automatic") or platform.get("UpdateSMBIOS") or generic not in ("", MODEL):
        raise FinishError("This OpenCore config uses automatic or spoofed model information; "
                          "review it in OCLP instead of overwriting it.")
    for key, expected in (("SystemProductName", MODEL), ("BoardProduct", BOARD)):
        current = platform["DataHub"].get(key)
        if current not in (None, "", expected):
            raise FinishError("Conflicting DataHub " + key + ": " + repr(current) + "; no config changed.")
        platform["DataHub"][key] = expected
    platform["UpdateDataHub"] = True
    return config


def save_config(path, before, expected):
    if path.read_bytes() != before:
        raise FinishError("Internal EFI config changed while checking; review it before retrying.")
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    backup = safe_path(path.parent, "config.before-finish-install-" + stamp + ".plist")
    with backup.open("xb") as saved:
        saved.write(before)
        saved.flush()
        os.fsync(saved.fileno())
    fd, temporary = tempfile.mkstemp(prefix=".finish-config-", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as out:
            out.write(plistlib.dumps(expected, sort_keys=False))
            out.flush()
            os.fsync(out.fileno())
        os.chmod(temporary, path.stat().st_mode & 0o777)
        if path.read_bytes() != before:
            raise FinishError("Internal EFI config changed before replacement; original backup: " + str(backup))
        os.replace(temporary, path)
        if plistlib.loads(path.read_bytes()) != expected:
            raise FinishError("Internal EFI read-back failed; restore original backup: " + str(backup))
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return backup


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Audit only; mount an unmounted EFI read-only")
    args = parser.parse_args(argv)
    if sys.version_info < (3, 9):
        raise FinishError("Python 3.9 or newer is required.")
    host = validate_host()
    if os.geteuid() != 0:
        command = ["/usr/bin/sudo", sys.executable, "-I", "-B", str(Path(__file__).resolve())]
        command.extend(["--check"] if args.check else [])
        os.execv(command[0], command)
    print("Running Mac:", host["model"], "— macOS", host["macos_version"], "(" + host["macos_build"] + ")")
    initial = internal_efi()
    with mounted_efi(initial, args.check) as mount:
        path = safe_path(mount, "EFI/OC/config.plist")
        if not path.is_file():
            raise FinishError("Internal OpenCore is missing. Build and Install OpenCore to the "
                              "INTERNAL drive's EFI in OCLP first, then rerun before rebooting.")
        before = path.read_bytes()
        original = plistlib.loads(before)
        if not isinstance(original, dict):
            raise FinishError("Expected an OpenCore plist dictionary.")
        print("Internal EFI:", initial["DeviceIdentifier"], "—", path)
        platform = original.get("PlatformInfo", {})
        datahub = platform.get("DataHub", {}) if isinstance(platform, dict) else {}
        if isinstance(datahub, dict):
            print("DataHub/SystemProductName:", repr(datahub.get("SystemProductName")))
            print("DataHub/BoardProduct:", repr(datahub.get("BoardProduct")))
        print("PlatformInfo/UpdateDataHub:", repr(platform.get("UpdateDataHub"))
              if isinstance(platform, dict) else "missing")
        expected = corrected_config(original)
        layout = check_boot_files(mount, original)
        if args.check:
            if expected != original:
                raise FinishError("Internal EFI needs the DataHub fix. Run again without --check.")
            print("PASS: internal EFI files and DataHub settings verify. USB-free boot still needs testing.")
            return
        stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        report_dir = safe_path(BASE, "build/internal-efi/" + stamp)
        report_dir.mkdir(parents=True)
        safe_path(BASE, "build/internal-efi/" + stamp + "/config.before.plist").write_bytes(before)
        report_path = safe_path(BASE, "build/internal-efi/" + stamp + "/report.json")
        report = dict(host, status="incomplete", efi_device=initial["DeviceIdentifier"],
                      efi_uuid=initial["DiskUUID"], system_identity=initial["SystemIdentity"],
                      boot_layout=layout, changed=False, usb_free_boot_verified=False)
        try:
            if validate_host() != host:
                raise FinishError("Running Mac identity changed; no config write.")
            same_efi(initial, internal_efi(), include_system=True)
            current = disk_info(initial["DeviceIdentifier"])
            same_efi(initial, current)
            if current.get("MountPoint") != str(mount):
                raise FinishError("Internal EFI mount changed; no config write.")
            safe_path(mount, "EFI/OC/config.plist")
            if path.read_bytes() != before:
                raise FinishError("Internal EFI config changed while checking; no config write.")
            if expected != original:
                report["efi_backup"] = str(save_config(path, before, expected))
                report["changed"] = True
            if plistlib.loads(path.read_bytes()) != expected:
                raise FinishError("Internal EFI settings did not verify. Keep the working USB connected.")
            report["boot_layout"] = check_boot_files(mount, expected)
            report["status"] = "configuration-verified-awaiting-boot-test"
        except Exception as exc:
            report["error"] = str(exc)
            raise
        finally:
            report_path.write_text(json.dumps(report, indent=2) + "\n")
            print("Internal EFI backup/report:", report_dir)
    print("PASS: internal EFI configuration verified; this is not a USB-free boot result.")
    print("Shut down, unplug the USB, start holding Option, and select INTERNAL EFI Boot, then Macintosh HD.")
    print("If boot fails, reconnect the unchanged USB and boot through its EFI Boot. Do not erase Tahoe.")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, subprocess.CalledProcessError) as exc:
        raise SystemExit("STOP: " + str(exc))
