"""Autopatch Rescue: fixtures only, no network, no real disks or disk images."""
import contextlib
import hashlib
import io
import json
from pathlib import Path
import plistlib
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import autopatch_rescue as rescue

ASSETS_BYTES = b"official AutoPkg-Assets fixture"
KDK_DMG_BYTES = b"official KDK disk image fixture"
KDK_PKG_BYTES = b"Apple KernelDebugKit.pkg fixture"


def sha(data):
    return hashlib.sha256(data).hexdigest()


def asset(name, data, digest=True):
    entry = {"name": name, "browser_download_url": "https://example.invalid/" + name, "size": len(data)}
    if digest:
        entry["digest"] = "sha256:" + sha(data)
    return entry


class RescueTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.usb, self.cache, self.mount = root / "usb", root / "cache", root / "kdkmount"
        version = self.usb / "System/Library/CoreServices/SystemVersion.plist"
        version.parent.mkdir(parents=True)
        version.write_bytes(plistlib.dumps({"ProductVersion": "26.7.2", "ProductBuildVersion": "25G332"}))
        (self.usb / "Install macOS Tahoe.app").mkdir()
        self.mount.mkdir()
        (self.mount / "KernelDebugKit.pkg").write_bytes(KDK_PKG_BYTES)
        self.releases = {
            "dortania/OpenCore-Legacy-Patcher@3.0.0-rc.5": {"assets": [asset("AutoPkg-Assets.pkg", ASSETS_BYTES)]},
            "dortania/KdkSupportPkg@25G332": {"assets": [asset("Kernel_Debug_Kit_26.7.2_build_25G332.dmg", KDK_DMG_BYTES)]},
        }
        self.files = {"AutoPkg-Assets.pkg": ASSETS_BYTES, "Kernel_Debug_Kit_26.7.2_build_25G332.dmg": KDK_DMG_BYTES}
        self.downloads = []

        def fake_release(repo, tag):
            return self.releases.get(f"{repo}@{tag}")

        def fake_urlopen(request, timeout=None):
            name = request.full_url.rsplit("/", 1)[1]
            self.downloads.append(name)
            return io.BytesIO(self.files[name])

        @contextlib.contextmanager
        def fake_mounted(dmg):
            yield self.mount

        for target, value in [
            ("release", fake_release),
            ("mounted", fake_mounted),
            ("apple_signed", lambda pkg: Path(pkg).read_bytes() == KDK_PKG_BYTES),
            ("disk_info", lambda path: {"Internal": False, "MountPoint": str(self.usb)}),
        ]:
            patcher = patch.object(rescue, target, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = patch.object(rescue.urllib.request, "urlopen", fake_urlopen)
        patcher.start()
        self.addCleanup(patcher.stop)

    def run_main(self, *extra):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = rescue.main(["--usb", str(self.usb), "--oclp-tag", "3.0.0-rc.5",
                                "--cache", str(self.cache), *extra])
        return code, out.getvalue()

    def packages(self):
        return self.usb / "Library/Packages"

    def test_incomplete_usb_gets_both_packages_and_passes(self):
        code, out = self.run_main()
        self.assertEqual(code, 0, out)
        self.assertEqual((self.packages() / "AutoPkg-Assets.pkg").read_bytes(), ASSETS_BYTES)
        self.assertEqual((self.packages() / "KDK.pkg").read_bytes(), KDK_PKG_BYTES)
        state = json.loads((self.usb / ".autopatch-rescue.json").read_text())
        self.assertEqual(sorted(p.name for p in self.packages().iterdir()), ["AutoPkg-Assets.pkg", "KDK.pkg"])
        self.assertEqual((state["oclp_tag"], state["macos_build"], state["kdk_build"]), ("3.0.0-rc.5", "25G332", "25G332"))
        self.assertIn("PASS", out)
        self.assertEqual(list(self.packages().glob(".*.part")), [])

    def test_second_run_downloads_nothing(self):
        self.run_main()
        self.downloads.clear()
        code, out = self.run_main()
        self.assertEqual(code, 0)
        self.assertEqual(self.downloads, [])
        self.assertIn("Nothing to do", out)

    def test_check_reports_without_writing(self):
        code, out = self.run_main("--check")
        self.assertEqual(code, 1)
        self.assertIn("AutoPkg-Assets.pkg: MISSING", out)
        self.assertFalse(self.packages().exists())
        self.assertEqual(self.downloads, [])

    def test_check_passes_after_fix(self):
        self.run_main()
        code, out = self.run_main("--check")
        self.assertEqual(code, 0)
        self.assertIn("PASS", out)

    def test_wrong_assets_package_is_replaced(self):
        self.packages().mkdir(parents=True)
        (self.packages() / "AutoPkg-Assets.pkg").write_bytes(b"RC3 or truncated package")
        code, _ = self.run_main()
        self.assertEqual(code, 0)
        self.assertEqual((self.packages() / "AutoPkg-Assets.pkg").read_bytes(), ASSETS_BYTES)

    def test_correct_assets_kept_when_only_kdk_missing(self):
        self.packages().mkdir(parents=True)
        (self.packages() / "AutoPkg-Assets.pkg").write_bytes(ASSETS_BYTES)
        code, out = self.run_main()
        self.assertEqual(code, 0)
        self.assertNotIn("AutoPkg-Assets.pkg", self.downloads)
        self.assertIn("AutoPkg-Assets.pkg already correct", out)

    def test_corrupt_download_is_rejected_and_not_cached(self):
        self.files["AutoPkg-Assets.pkg"] = b"x" * len(ASSETS_BYTES)
        code, out = self.run_main()
        self.assertEqual(code, 2)
        self.assertIn("does not match GitHub's SHA-256 digest", out)
        self.assertFalse((self.packages() / "AutoPkg-Assets.pkg").exists())
        self.assertEqual(list(self.cache.iterdir()), [])

    def test_html_error_page_like_the_rc_bug_is_rejected(self):
        self.files["AutoPkg-Assets.pkg"] = b"<html>301 Moved Permanently</html>"
        code, out = self.run_main()
        self.assertEqual(code, 2)
        self.assertIn("Incomplete download", out)

    def test_asset_without_published_digest_is_refused(self):
        self.releases["dortania/OpenCore-Legacy-Patcher@3.0.0-rc.5"] = {"assets": [asset("AutoPkg-Assets.pkg", ASSETS_BYTES, digest=False)]}
        code, out = self.run_main()
        self.assertEqual(code, 2)
        self.assertIn("no SHA-256 digest", out)

    def test_missing_kdk_release_explains_override(self):
        del self.releases["dortania/KdkSupportPkg@25G332"]
        code, out = self.run_main()
        self.assertEqual(code, 2)
        self.assertIn("--kdk-build", out)

    def test_kdk_build_override_is_used(self):
        self.releases["dortania/KdkSupportPkg@25G331"] = self.releases.pop("dortania/KdkSupportPkg@25G332")
        code, out = self.run_main("--kdk-build", "25G331")
        self.assertEqual(code, 0, out)

    def test_unsigned_kdk_package_is_refused(self):
        (self.mount / "KernelDebugKit.pkg").write_bytes(b"not apple signed")
        code, out = self.run_main()
        self.assertEqual(code, 2)
        self.assertIn("Apple-signed", out)
        self.assertFalse((self.packages() / "KDK.pkg").exists())

    def test_internal_disk_is_refused(self):
        with patch.object(rescue, "disk_info", lambda path: {"Internal": True, "MountPoint": str(self.usb)}):
            code, out = self.run_main()
        self.assertEqual(code, 2)
        self.assertIn("not an internal disk", out)

    def test_non_installer_volume_is_refused(self):
        (self.usb / "Install macOS Tahoe.app").rmdir()
        code, out = self.run_main()
        self.assertEqual(code, 2)
        self.assertIn("not a macOS installer USB", out)

    def test_pre_big_sur_installer_is_refused(self):
        (self.usb / "System/Library/CoreServices/SystemVersion.plist").write_bytes(
            plistlib.dumps({"ProductVersion": "10.15.7", "ProductBuildVersion": "19H15"}))
        code, out = self.run_main()
        self.assertEqual(code, 2)
        self.assertIn("Big Sur", out)

    def test_low_space_stops_before_writing(self):
        with patch.object(rescue, "free_space", lambda path: 10):
            code, out = self.run_main()
        self.assertEqual(code, 2)
        self.assertIn("free", out)
        self.assertFalse((self.packages() / "AutoPkg-Assets.pkg").exists())

    def test_tag_is_read_from_installed_app(self):
        app = Path(self.tmp.name) / "OpenCore-Patcher.app"
        (app / "Contents").mkdir(parents=True)
        (app / "Contents/Info.plist").write_bytes(plistlib.dumps({"Github": {"Branch": "refs/tags/3.0.0-rc.5"}}))
        self.assertEqual(rescue.installed_oclp_tag(app), "3.0.0-rc.5")

    def test_untagged_or_missing_app_asks_for_tag(self):
        app = Path(self.tmp.name) / "OpenCore-Patcher.app"
        with self.assertRaisesRegex(rescue.FixError, "not installed"):
            rescue.installed_oclp_tag(app)
        (app / "Contents").mkdir(parents=True)
        (app / "Contents/Info.plist").write_bytes(plistlib.dumps({"Github": {"Branch": "main"}}))
        with self.assertRaisesRegex(rescue.FixError, "--oclp-tag"):
            rescue.installed_oclp_tag(app)


if __name__ == "__main__":
    unittest.main()
