#!/usr/bin/env python3
"""Autopatch Rescue: complete an OpenCore Legacy Patcher (OCLP) installer USB.

Works for any Mac model. OCLP's "Create macOS Installer" is meant to put two
packages in the installer's Library/Packages folder:

  AutoPkg-Assets.pkg  OCLP app, helper and patch resources. After macOS is
                      installed it installs OCLP and root patches automatically.
  KDK.pkg             Apple's Kernel Debug Kit for the installer's macOS build,
                      so that first-boot root patching works without internet.

During the OCLP 3.0.0 release candidates that download fails without any
warning (see docs/OCLP-RC-ASSETS-BUG.md), so the USB is left without both.

This script reads the installer's macOS build and the OCLP release tag, then
adds exactly the official files OCLP would have added, each verified against
the SHA-256 digest GitHub publishes for it. Correct files already present are
kept. A package that does not match is deleted and downloaded again, never
edited. Nothing is installed on this Mac and no disk is erased.

It also checks the OpenCore that OCLP installed on the USB's EFI partition.
When OCLP built it for the Mac's own model (no SMBIOS spoof) and left the
DataHub model and board ID empty, it fills in that model's real values from
OCLP's own model table. OCLP does this itself only for Ivy Bridge and older
Macs; without it a newer Mac can loop at boot on "failed to obtain model
information". The config is backed up first, and values that are already set
are never overwritten.

It shows what the USB is for and what's missing, and asks before changing
anything.

  python3 autopatch_rescue.py --usb "/Volumes/Install macOS Tahoe"           # fix (asks for your password)
  python3 autopatch_rescue.py --usb "/Volumes/Install macOS Tahoe" --check   # report only
"""
import argparse
import contextlib
import datetime
import hashlib
import json
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

OCLP_REPO = "dortania/OpenCore-Legacy-Patcher"
KDK_REPO = "dortania/KdkSupportPkg"
OCLP_APP = Path("/Library/Application Support/Dortania/OpenCore-Patcher.app")
# Under sudo, keep the download cache in the invoking user's home, not root's.
HOME = Path(os.path.expanduser("~" + os.environ.get("SUDO_USER", "")))
CACHE = HOME / "Library/Caches/autopatch-rescue"
OCLP_GUID = "4D1FDA02-38C7-4A6A-9CC6-4BCCA8B30102"
MODELS_FILE = Path(__file__).resolve().with_name("oclp_models.json")
APPLE_GUID = "7C436110-AB2A-4BBB-A880-FE41995C9F82"
ASSETS = "AutoPkg-Assets.pkg"
KDK = "KDK.pkg"
STATE = ".autopatch-rescue.json"
USER_AGENT = "autopatch-rescue"
MIN_MACOS_MAJOR = 11  # OCLP only adds these packages to Big Sur and newer installers


class FixError(Exception):
    """A problem the user must resolve; printed without a traceback."""


def say(*parts):
    print(*parts, flush=True)


# ---------------------------------------------------------------- hashing / IO

def sha256(path, label=None):
    path = Path(path)
    total = path.stat().st_size
    h = hashlib.sha256()
    done, last = 0, time.monotonic()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
            done += len(block)
            if label and total > 64 * 1024 ** 2 and time.monotonic() - last >= 2:
                say(f"  checking {label}: {done * 100 // total}%")
                last = time.monotonic()
    return h.hexdigest()


def copy_verified(source, dest, expected_sha):
    """Copy via a temporary name on the same volume, verify, then rename."""
    dest = Path(dest)
    tmp = dest.with_name("." + dest.name + ".part")
    try:
        shutil.copyfile(source, tmp)
        if sha256(tmp, dest.name) != expected_sha:
            raise FixError(f"Copy to the USB did not verify: {dest}")
        os.chmod(tmp, 0o644)
        os.replace(tmp, dest)
    finally:
        if tmp.exists():
            tmp.unlink()


def remove(path, why):
    """Packages are never edited in place: a file that does not match is deleted."""
    path = Path(path)
    if path.exists():
        say(f"  deleting {path.name}: {why}")
        path.unlink()


def free_space(path):
    return shutil.disk_usage(path).free


# --------------------------------------------------------------------- network

def fetch_json(url):
    request = urllib.request.Request(url, headers={
        "Accept": "application/vnd.github+json", "User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        if error.code == 404:
            return None
        raise FixError(f"GitHub answered HTTP {error.code} for {url}") from error
    except urllib.error.URLError as error:
        raise FixError(f"Could not reach GitHub ({error.reason}). Check the internet connection and rerun.") from error


def release(repo, tag):
    return fetch_json(f"https://api.github.com/repos/{repo}/releases/tags/{tag}")


def release_asset(rel, matches):
    """Return (name, url, size, sha256) for the first asset whose name matches."""
    for asset in rel.get("assets", []):
        if matches(asset["name"]):
            digest = asset.get("digest") or ""
            if not digest.startswith("sha256:") or len(digest) != 71:
                raise FixError(f"GitHub publishes no SHA-256 digest for {asset['name']}; refusing an unverifiable file.")
            return asset["name"], asset["browser_download_url"], asset["size"], digest[7:]
    return None


def download(url, name, size, expected_sha, cache):
    """Download into the cache (reused when already verified) and return its path."""
    cache.mkdir(parents=True, exist_ok=True)
    dest = cache / name
    if dest.is_file():
        if dest.stat().st_size == size and sha256(dest, name) == expected_sha:
            say(f"  using verified cached {name}")
            return dest
        remove(dest, "cached copy does not match GitHub's SHA-256 digest")
    say(f"  downloading {name} ({size / 1024 ** 2:.0f} MiB) from {url}")
    fd, tmp = tempfile.mkstemp(prefix=name + ".", suffix=".part", dir=str(cache))
    try:
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with os.fdopen(fd, "wb") as out, urllib.request.urlopen(request, timeout=120) as response:
            received, last = 0, time.monotonic()
            for block in iter(lambda: response.read(1024 * 1024), b""):
                out.write(block)
                received += len(block)
                if time.monotonic() - last >= 3:
                    say(f"  {name}: {received * 100 // max(size, 1)}% ({received / 1024 ** 2:.0f} MiB)")
                    last = time.monotonic()
        if received != size:
            raise FixError(f"Incomplete download of {name}: {received} of {size} bytes. Rerun to retry.")
        if sha256(tmp, name) != expected_sha:
            raise FixError(f"Downloaded {name} does not match GitHub's SHA-256 digest.")
        os.replace(tmp, dest)
        if os.environ.get("SUDO_UID"):  # keep the cache usable without sudo next time
            for owned in (cache, dest):
                os.chown(owned, int(os.environ["SUDO_UID"]), int(os.environ.get("SUDO_GID", "-1")))
    except urllib.error.URLError as error:
        raise FixError(f"Download of {name} failed ({getattr(error, 'reason', error)}). Rerun to retry.") from error
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    return dest


# ------------------------------------------------------------------ the inputs

def disk_info(path):
    return plistlib.loads(subprocess.check_output(["/usr/sbin/diskutil", "info", "-plist", str(path)]))


def read_installer(usb):
    """Validate the USB is an external macOS installer; return (version, build)."""
    usb = Path(usb)
    if not usb.is_dir():
        raise FixError(f"{usb} is not a mounted volume.")
    info = disk_info(usb)
    if info.get("Internal") is not False:
        raise FixError("Choose the external installer USB, not an internal disk.")
    if Path(info.get("MountPoint", "")).resolve() != usb.resolve():
        raise FixError("--usb must be the USB volume itself, for example \"/Volumes/Install macOS Tahoe\".")
    plist = usb / "System/Library/CoreServices/SystemVersion.plist"
    if not plist.is_file() or not list(usb.glob("Install macOS*.app")):
        raise FixError("This volume is not a macOS installer USB. Create it with OCLP's Create macOS Installer first.")
    data = plistlib.loads(plist.read_bytes())
    version, build = data.get("ProductVersion", ""), data.get("ProductBuildVersion", "")
    if not version or not build:
        raise FixError("The installer's macOS version could not be read.")
    if int(version.split(".")[0]) < MIN_MACOS_MAJOR:
        raise FixError(f"macOS {version} installers do not use these packages (Big Sur 11 or newer only).")
    return version, build


def installed_oclp_tag(app=OCLP_APP):
    """Release tag of the installed OCLP app, e.g. 3.0.0-rc.5 (its window only shows 3.0.0)."""
    plist = Path(app) / "Contents/Info.plist"
    if not plist.is_file():
        raise FixError(f"OCLP is not installed at {app}. Install it, or pass --oclp-tag.")
    branch = plistlib.loads(plist.read_bytes()).get("Github", {}).get("Branch", "")
    if not branch.startswith("refs/tags/"):
        raise FixError("The installed OCLP is not a tagged release build. Pass --oclp-tag, for example 3.0.0-rc.5.")
    return branch[len("refs/tags/"):]


# -------------------------------------------------------------------- the KDK

@contextlib.contextmanager
def mounted(dmg):
    mount = tempfile.mkdtemp(prefix="oclp-kdk-")
    subprocess.run(["/usr/bin/hdiutil", "attach", str(dmg), "-readonly", "-nobrowse",
                    "-mountpoint", mount, "-quiet"], check=True)
    try:
        yield Path(mount)
    finally:
        subprocess.run(["/usr/bin/hdiutil", "detach", mount, "-quiet"], check=False)
        with contextlib.suppress(OSError):
            os.rmdir(mount)


def apple_signed(pkg):
    result = subprocess.run(["/usr/sbin/pkgutil", "--check-signature", str(pkg)],
                            capture_output=True, text=True)
    return result.returncode == 0 and "signed Apple Software" in result.stdout


# ------------------------------------------------------------------- the work

def plan(usb, oclp_tag, kdk_build):
    """Work out what the USB should contain. Network: GitHub API only."""
    version, build = read_installer(usb)
    kdk_build = kdk_build or build

    rel = release(OCLP_REPO, oclp_tag)
    if rel is None:
        raise FixError(f"OCLP release {oclp_tag} was not found on GitHub.")
    assets = release_asset(rel, lambda name: name == ASSETS)
    if assets is None:
        raise FixError(f"OCLP release {oclp_tag} has no {ASSETS}.")

    kdk_rel = release(KDK_REPO, kdk_build)
    if kdk_rel is None:
        raise FixError(f"Dortania has no Kernel Debug Kit for build {kdk_build} yet. "
                       "Wait for one, or pass --kdk-build with the closest build OCLP itself would use.")
    kdk = release_asset(kdk_rel, lambda name: name.endswith(".dmg"))
    if kdk is None:
        raise FixError(f"KdkSupportPkg release {kdk_build} has no disk image.")
    return {"macos_version": version, "macos_build": build, "oclp_tag": oclp_tag,
            "kdk_build": kdk_build, "assets": assets, "kdk": kdk}


def inspect(usb, want):
    """Return (assets_ok, kdk_ok, state) for what is on the USB now."""
    packages = Path(usb) / "Library/Packages"
    state_path = Path(usb) / STATE  # kept out of Library/Packages, which holds only installer packages
    try:
        state = json.loads(state_path.read_text())
    except (OSError, ValueError):
        state = {}
    assets_path = packages / ASSETS
    assets_ok = assets_path.is_file() and assets_path.stat().st_size == want["assets"][2] \
        and sha256(assets_path, ASSETS) == want["assets"][3]
    kdk_path = packages / KDK
    kdk_ok = (kdk_path.is_file() and state.get("kdk_dmg_sha256") == want["kdk"][3]
              and state.get("kdk_pkg_sha256") == sha256(kdk_path, KDK) and apple_signed(kdk_path))
    return assets_ok, kdk_ok, state


def fix(usb, want, cache):
    usb = Path(usb)
    packages = usb / "Library/Packages"
    assets_ok, kdk_ok, state = inspect(usb, want)
    if assets_ok and kdk_ok:
        say("Nothing to do: both packages are already present and verified.")
        return state

    packages.mkdir(parents=True, exist_ok=True)
    for leftover in packages.glob(".*.part"):
        remove(leftover, "unfinished copy from an earlier run")
    if not assets_ok:
        remove(packages / ASSETS, "does not match the official package for OCLP " + want["oclp_tag"])
    if not kdk_ok:
        remove(packages / KDK, "not verified as the Apple KDK for build " + want["kdk_build"])
        state.pop("kdk_pkg_sha256", None)
        state.pop("kdk_dmg_sha256", None)
    needed = (0 if assets_ok else want["assets"][2]) + (0 if kdk_ok else want["kdk"][2])
    if free_space(usb) < needed + 64 * 1024 ** 2:
        raise FixError(f"The USB needs about {needed / 1024 ** 3:.1f} GiB free for the missing packages.")

    if not assets_ok:
        name, url, size, sha = want["assets"]
        say(f"Adding {ASSETS} from OCLP {want['oclp_tag']}")
        copy_verified(download(url, name, size, sha, cache), packages / ASSETS, sha)
    else:
        say(f"{ASSETS} already correct")

    if not kdk_ok:
        name, url, size, sha = want["kdk"]
        say(f"Adding {KDK} for build {want['kdk_build']}")
        dmg = download(url, name, size, sha, cache)
        with mounted(dmg) as mount:
            source = mount / "KernelDebugKit.pkg"
            if not source.is_file() or not apple_signed(source):
                raise FixError(f"{name} does not contain an Apple-signed KernelDebugKit.pkg.")
            pkg_sha = sha256(source, "KernelDebugKit.pkg")
            copy_verified(source, packages / KDK, pkg_sha)
        state["kdk_pkg_sha256"] = pkg_sha
        state["kdk_dmg_sha256"] = sha
    else:
        say(f"{KDK} already correct")

    state.update({"oclp_tag": want["oclp_tag"], "assets_sha256": want["assets"][3],
                  "macos_build": want["macos_build"], "kdk_build": want["kdk_build"],
                  "kdk_dmg": want["kdk"][0]})
    (usb / STATE).write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")
    return state


# ------------------------------------------------- OpenCore DataHub on the EFI

MACOS_NAMES = {"11": "Big Sur", "12": "Monterey", "13": "Ventura", "14": "Sonoma", "15": "Sequoia", "26": "Tahoe"}


def models():
    return json.loads(MODELS_FILE.read_text())["models"]


def board_ids():
    return {model: info["board_id"] for model, info in models().items()}


def efi_partition(usb):
    """The EFI partition on the same physical USB as the installer volume."""
    whole = disk_info(usb).get("ParentWholeDisk")
    if not whole:
        raise FixError("Could not identify the USB's disk.")
    listing = plistlib.loads(subprocess.check_output(["/usr/sbin/diskutil", "list", "-plist", whole]))
    for disk in listing.get("AllDisksAndPartitions", []):
        for part in disk.get("Partitions", []):
            if part.get("Content") == "EFI":
                return part["DeviceIdentifier"]
    raise FixError("The USB has no EFI partition. Recreate it with OCLP's Create macOS Installer.")


@contextlib.contextmanager
def efi_mounted(device):
    """Yield the EFI mount point, mounting it (and unmounting afterwards) if needed."""
    current = disk_info(device).get("MountPoint")
    if current:
        yield Path(current)
        return
    result = subprocess.run(["/usr/sbin/diskutil", "mount", device], capture_output=True, text=True)
    if result.returncode != 0:
        if os.geteuid() != 0:
            raise FixError("Opening the USB's EFI partition needs administrator rights. Rerun with sudo.")
        raise FixError(f"diskutil could not mount {device}: {(result.stdout + result.stderr).strip()}")
    try:
        yield Path(disk_info(device)["MountPoint"])
    finally:
        subprocess.run(["/usr/sbin/diskutil", "unmount", device], capture_output=True)


def datahub_status(config):
    """Describe the OpenCore config: status is ok, missing or spoofed."""
    model = config.get("NVRAM", {}).get("Add", {}).get(OCLP_GUID, {}).get("OCLP-Model")
    if not model:
        raise FixError("The USB's OpenCore was not built by OCLP (no OCLP-Model). "
                       "In OCLP, set the Target Model, then Build and Install OpenCore onto this USB.")
    original = config.get("#Revision", {}).get("Original-Model")
    if original and original != model:
        raise FixError(f"OpenCore config is inconsistent: built for {original}, labelled {model}. Rebuild it in OCLP.")
    platform = config.get("PlatformInfo")
    if not isinstance(platform, dict) or not isinstance(platform.get("DataHub"), dict):
        raise FixError("OpenCore config has no PlatformInfo/DataHub section. Rebuild it in OCLP.")
    info = models().get(model, {})
    boot_args = config.get("NVRAM", {}).get("Add", {}).get(APPLE_GUID, {}).get("boot-args", "")
    result = {"model": model, "name": info.get("name", model), "board": info.get("board_id"),
              "verbose": "-v" in str(boot_args).split(), "spoof": None, "missing": []}
    generic = platform.get("Generic", {}).get("SystemProductName", "")
    if platform.get("UpdateSMBIOS") or (generic and generic != model):
        result.update(status="spoofed", spoof=generic or "another model")  # OCLP set it on purpose
        return result
    if not result["board"]:
        raise FixError(f"OCLP's model table has no board ID for {model}.")
    datahub = platform["DataHub"]
    for key, want in (("SystemProductName", model), ("BoardProduct", result["board"])):
        if datahub.get(key) not in ("", None, want):
            raise FixError(f"DataHub {key} is {datahub.get(key)!r}, expected {want!r} for {model}. "
                           "It was set by someone else; review it rather than overwrite.")
        if datahub.get(key) != want:
            result["missing"].append(key)
    if platform.get("UpdateDataHub") is not True:
        result["missing"].append("UpdateDataHub")
    result["status"] = "missing" if result["missing"] else "ok"
    return result


def set_datahub(path, model, board):
    original_bytes = path.read_bytes()
    config = plistlib.loads(original_bytes)
    config["PlatformInfo"]["DataHub"]["SystemProductName"] = model
    config["PlatformInfo"]["DataHub"]["BoardProduct"] = board
    config["PlatformInfo"]["UpdateDataHub"] = True
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = path.with_name(f"config.before-autopatch-rescue-{stamp}.plist")
    with backup.open("xb") as out:
        out.write(original_bytes)
    fd, temp = tempfile.mkstemp(prefix=".config-", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as out:
            out.write(plistlib.dumps(config, sort_keys=False))
            out.flush()
            os.fsync(out.fileno())
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)
    if plistlib.loads(path.read_bytes()) != config:
        raise FixError(f"OpenCore config did not read back correctly; restore {backup}")
    return backup


def efi_config(mount):
    path = mount / "EFI/OC/config.plist"
    if not path.is_file():
        raise FixError("The USB's EFI has no OpenCore yet. In OCLP, set the Target Model, "
                       "then Build and Install OpenCore onto this USB.")
    return path


def efi_read(usb):
    with efi_mounted(efi_partition(usb)) as mount:
        return datahub_status(plistlib.loads(efi_config(mount).read_bytes()))


def efi_fix(usb):
    """Write the missing DataHub values. Returns the status afterwards."""
    with efi_mounted(efi_partition(usb)) as mount:
        path = efi_config(mount)
        status = datahub_status(plistlib.loads(path.read_bytes()))
        if status["status"] != "missing":
            return status
        backup = set_datahub(path, status["model"], status["board"])
        say(f"  DataHub set: SystemProductName={status['model']}, BoardProduct={status['board']}, UpdateDataHub=true")
        say(f"  original config saved on the USB's EFI as EFI/OC/{backup.name}")
        return datahub_status(plistlib.loads(path.read_bytes()))


# ----------------------------------------------------------------- the report

def report(want, assets_ok, kdk_ok, efi):
    """Show what this USB will install and what is missing. Returns True if anything needs fixing."""
    version = want["macos_version"]
    say("")
    say("This USB")
    say(f"  macOS installer:     {MACOS_NAMES.get(version.split('.')[0], 'macOS')} {version} ({want['macos_build']})")
    say(f"  OCLP release:        {want['oclp_tag']}")
    if efi:
        say(f"  OpenCore built for:  {efi['name']} ({efi['model']})")
        say(f"  Verbose boot:        {'on' if efi['verbose'] else 'off (turn on in OCLP settings to see boot messages)'}")
    say("")
    say("Checks")
    say(f"  {ASSETS:<20} {'OK' if assets_ok else 'MISSING -> download from OCLP ' + want['oclp_tag']}")
    say(f"  {KDK:<20} {'OK' if kdk_ok else 'MISSING -> add Apple KDK for ' + want['kdk_build']}")
    if efi:
        if efi["status"] == "spoofed":
            say(f"  {'DataHub':<20} left alone (OCLP built it spoofed as {efi['spoof']})")
        elif efi["status"] == "ok":
            say(f"  {'DataHub':<20} OK ({efi['model']}, {efi['board']})")
        else:
            say(f"  {'DataHub':<20} MISSING {', '.join(efi['missing'])} -> set {efi['model']}, {efi['board']}, UpdateDataHub on")
    say("")
    return not (assets_ok and kdk_ok and (efi is None or efi["status"] != "missing"))


def confirm(efi, assume_yes):
    """Ask before changing anything: the USB must be for the Mac being installed."""
    if assume_yes:
        return True
    if not sys.stdin.isatty():
        raise FixError("Run this in Terminal so it can ask you to confirm, or add --yes.")
    target = f"{efi['name']} ({efi['model']})" if efi else "the Mac you chose in OCLP"
    say(f"This USB is set up for: {target}")
    try:
        answer = input("Is that the Mac you're installing on, and should the changes above be made? [y/N] ")
    except EOFError:
        answer = ""
    return answer.strip().lower() in ("y", "yes")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--usb", required=True, type=Path, help='Installer volume, e.g. "/Volumes/Install macOS Tahoe"')
    parser.add_argument("--check", action="store_true", help="Report only; change nothing")
    parser.add_argument("--yes", action="store_true", help="Don't ask for confirmation before making changes")
    parser.add_argument("--oclp-tag", help="OCLP release tag (default: read from the installed OCLP app)")
    parser.add_argument("--kdk-build", help="KDK build to use when no exact match exists (default: the installer's build)")
    parser.add_argument("--cache", type=Path, default=CACHE, help=f"Download cache (default: {CACHE})")
    parser.add_argument("--packages-only", action="store_true", help="Skip the OpenCore DataHub check on the EFI")
    args = parser.parse_args(argv)
    if argv is None and not args.packages_only and os.geteuid() != 0:
        # The USB's EFI partition can only be opened as administrator, so ask once, up front.
        say("Autopatch Rescue needs your Mac password to open the USB's EFI partition.")
        os.execv("/usr/bin/sudo", ["sudo", sys.executable, str(Path(__file__).resolve())] + sys.argv[1:])
    try:
        want = plan(args.usb, args.oclp_tag or installed_oclp_tag(), args.kdk_build)
        assets_ok, kdk_ok, _ = inspect(args.usb, want)
        efi = None if args.packages_only else efi_read(args.usb)
        needs_work = report(want, assets_ok, kdk_ok, efi)

        if not needs_work:
            say("PASS: nothing is missing. The USB is ready.")
            return 0
        if args.check:
            say("Something is missing. Run again without --check to fix it.")
            return 1
        if not confirm(efi, args.yes):
            say("No changes made.")
            return 1

        if not (assets_ok and kdk_ok):
            fix(args.usb, want, args.cache)
            assets_ok, kdk_ok, _ = inspect(args.usb, want)
            if not (assets_ok and kdk_ok):
                raise FixError("Final check failed; the packages are still incomplete.")
            say("Packages: AutoPkg-Assets.pkg and KDK.pkg are on the USB and verified.")
        if efi and efi["status"] == "missing":
            if efi_fix(args.usb)["status"] != "ok":
                raise FixError("OpenCore DataHub check failed after the update.")
        say("PASS: the USB is ready. Eject it and boot the target Mac from the USB's EFI Boot.")
        return 0
    except FixError as error:
        say("STOP:", error)
        return 2


if __name__ == "__main__":
    sys.exit(main())
