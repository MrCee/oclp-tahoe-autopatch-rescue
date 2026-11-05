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

  python3 autopatch_rescue.py --usb "/Volumes/Install macOS Tahoe"           # fix
  python3 autopatch_rescue.py --usb "/Volumes/Install macOS Tahoe" --check   # report only
"""
import argparse
import contextlib
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
CACHE = Path.home() / "Library/Caches/autopatch-rescue"
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
    say(f"Installer: macOS {version} ({build})")
    say(f"OCLP release: {oclp_tag}")

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


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--usb", required=True, type=Path, help='Installer volume, e.g. "/Volumes/Install macOS Tahoe"')
    parser.add_argument("--check", action="store_true", help="Report only; change nothing")
    parser.add_argument("--oclp-tag", help="OCLP release tag (default: read from the installed OCLP app)")
    parser.add_argument("--kdk-build", help="KDK build to use when no exact match exists (default: the installer's build)")
    parser.add_argument("--cache", type=Path, default=CACHE, help=f"Download cache (default: {CACHE})")
    args = parser.parse_args(argv)
    try:
        want = plan(args.usb, args.oclp_tag or installed_oclp_tag(), args.kdk_build)
        if args.check:
            assets_ok, kdk_ok, _ = inspect(args.usb, want)
            say(f"{ASSETS}: {'OK' if assets_ok else 'MISSING or wrong'}")
            say(f"{KDK}: {'OK' if kdk_ok else 'MISSING or unverified'}")
            if assets_ok and kdk_ok:
                say("PASS: the USB has the packages OCLP should have added.")
                return 0
            say("Run again without --check to add them.")
            return 1
        fix(args.usb, want, args.cache)
        assets_ok, kdk_ok, _ = inspect(args.usb, want)
        if not (assets_ok and kdk_ok):
            raise FixError("Final check failed; the USB is still incomplete.")
        say("PASS: AutoPkg-Assets.pkg and KDK.pkg are on the USB and verified.")
        say("Next: in OCLP, Build and Install OpenCore for the target Mac onto this USB's EFI (if not done), then eject.")
        return 0
    except FixError as error:
        say("STOP:", error)
        return 2


if __name__ == "__main__":
    sys.exit(main())
