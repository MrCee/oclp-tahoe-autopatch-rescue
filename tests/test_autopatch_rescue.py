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
        self.efi = root / "efi"
        (self.efi / "EFI/OC").mkdir(parents=True)
        self.write_config()
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

        @contextlib.contextmanager
        def fake_efi_mounted(device):
            yield self.efi

        for target, value in [
            ("release", fake_release),
            ("mounted", fake_mounted),
            ("efi_mounted", fake_efi_mounted),
            ("efi_partition", lambda usb: "disk9s1"),
            ("apple_signed", lambda pkg: Path(pkg).read_bytes() == KDK_PKG_BYTES),
            ("disk_info", lambda path: {"Internal": False, "MountPoint": str(self.usb)}),
        ]:
            patcher = patch.object(rescue, target, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = patch.object(rescue.urllib.request, "urlopen", fake_urlopen)
        patcher.start()
        self.addCleanup(patcher.stop)

    def write_config(self, model="MacBookPro11,3", product="", board="", update=False, spoof=""):
        config = {
            "#Revision": {"Original-Model": model},
            "NVRAM": {"Add": {rescue.OCLP_GUID: {"OCLP-Model": model, "OCLP-Version": "3.0.0"}}},
            "PlatformInfo": {"DataHub": {"SystemProductName": product, "BoardProduct": board},
                             "Generic": {"SystemProductName": spoof}, "UpdateDataHub": update,
                             "UpdateSMBIOS": bool(spoof)},
        }
        (self.efi / "EFI/OC/config.plist").write_bytes(plistlib.dumps(config))

    def config(self):
        return plistlib.loads((self.efi / "EFI/OC/config.plist").read_bytes())

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

    def test_wrong_assets_package_is_deleted_then_downloaded(self):
        self.packages().mkdir(parents=True)
        (self.packages() / "AutoPkg-Assets.pkg").write_bytes(b"RC3 or truncated package")
        code, out = self.run_main()
        self.assertEqual(code, 0)
        self.assertIn("deleting AutoPkg-Assets.pkg: does not match", out)
        self.assertLess(out.index("deleting AutoPkg-Assets.pkg"), out.index("downloading AutoPkg-Assets.pkg"))
        self.assertEqual((self.packages() / "AutoPkg-Assets.pkg").read_bytes(), ASSETS_BYTES)

    def test_unverified_kdk_package_is_deleted_then_replaced(self):
        self.packages().mkdir(parents=True)
        (self.packages() / "KDK.pkg").write_bytes(b"KDK for another build")
        code, out = self.run_main()
        self.assertEqual(code, 0)
        self.assertIn("deleting KDK.pkg: not verified", out)
        self.assertEqual((self.packages() / "KDK.pkg").read_bytes(), KDK_PKG_BYTES)

    def test_mismatched_cached_download_is_deleted_and_downloaded_again(self):
        self.cache.mkdir()
        (self.cache / "AutoPkg-Assets.pkg").write_bytes(b"x" * len(ASSETS_BYTES))
        code, out = self.run_main()
        self.assertEqual(code, 0)
        self.assertIn("deleting AutoPkg-Assets.pkg: cached copy does not match", out)
        self.assertIn("AutoPkg-Assets.pkg", self.downloads)
        self.assertEqual((self.cache / "AutoPkg-Assets.pkg").read_bytes(), ASSETS_BYTES)

    def test_unfinished_copy_from_earlier_run_is_deleted(self):
        self.packages().mkdir(parents=True)
        (self.packages() / ".KDK.pkg.part").write_bytes(b"interrupted")
        code, out = self.run_main()
        self.assertEqual(code, 0)
        self.assertFalse((self.packages() / ".KDK.pkg.part").exists())
        self.assertIn("unfinished copy", out)

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

    def test_empty_datahub_is_filled_with_the_built_models_real_values(self):
        code, out = self.run_main()
        self.assertEqual(code, 0, out)
        platform = self.config()["PlatformInfo"]
        self.assertEqual(platform["DataHub"], {"SystemProductName": "MacBookPro11,3", "BoardProduct": "Mac-2BD1B31983FE1663"})
        self.assertIs(platform["UpdateDataHub"], True)
        backups = list((self.efi / "EFI/OC").glob("config.before-autopatch-rescue-*.plist"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(plistlib.loads(backups[0].read_bytes())["PlatformInfo"]["DataHub"]["BoardProduct"], "")

    def test_board_id_follows_the_model_oclp_built_for(self):
        self.write_config(model="iMac18,2")
        code, _ = self.run_main()
        self.assertEqual(code, 0)
        self.assertEqual(self.config()["PlatformInfo"]["DataHub"]["BoardProduct"], "Mac-77F17D7DA9285301")

    def test_correct_datahub_is_not_rewritten(self):
        self.write_config(product="MacBookPro11,3", board="Mac-2BD1B31983FE1663", update=True)
        code, out = self.run_main()
        self.assertEqual(code, 0)
        self.assertIn("DataHub: OK", out)
        self.assertEqual(list((self.efi / "EFI/OC").glob("config.before-*")), [])

    def test_spoofed_build_is_left_alone(self):
        self.write_config(spoof="MacBookPro14,1")
        code, out = self.run_main()
        self.assertEqual(code, 0)
        self.assertIn("left alone", out)
        self.assertEqual(self.config()["PlatformInfo"]["DataHub"]["SystemProductName"], "")

    def test_conflicting_datahub_value_is_never_overwritten(self):
        self.write_config(product="MacBookPro11,3", board="Mac-SOMETHINGELSE")
        code, out = self.run_main()
        self.assertEqual(code, 2)
        self.assertIn("review it rather than overwrite", out)
        self.assertEqual(self.config()["PlatformInfo"]["DataHub"]["BoardProduct"], "Mac-SOMETHINGELSE")

    def test_config_not_built_by_oclp_stops(self):
        (self.efi / "EFI/OC/config.plist").write_bytes(plistlib.dumps({"PlatformInfo": {"DataHub": {}}}))
        code, out = self.run_main()
        self.assertEqual(code, 2)
        self.assertIn("Build and Install OpenCore", out)

    def test_missing_opencore_on_efi_stops(self):
        (self.efi / "EFI/OC/config.plist").unlink()
        code, out = self.run_main()
        self.assertEqual(code, 2)
        self.assertIn("no OpenCore yet", out)

    def test_check_reports_missing_datahub_without_writing(self):
        self.run_main("--packages-only")
        code, out = self.run_main("--check")
        self.assertEqual(code, 1)
        self.assertIn("DataHub: MISSING", out)
        self.assertEqual(self.config()["PlatformInfo"]["DataHub"]["SystemProductName"], "")

    def test_packages_only_skips_efi(self):
        code, out = self.run_main("--packages-only")
        self.assertEqual(code, 0)
        self.assertNotIn("DataHub", out)
        self.assertEqual(self.config()["PlatformInfo"]["DataHub"]["SystemProductName"], "")

    def test_board_id_table_covers_oclp_models(self):
        ids = rescue.board_ids()
        self.assertGreater(len(ids), 100)
        self.assertEqual(ids["MacBookPro11,3"], "Mac-2BD1B31983FE1663")
        self.assertTrue(all(v.startswith("Mac-") for v in ids.values()))

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
