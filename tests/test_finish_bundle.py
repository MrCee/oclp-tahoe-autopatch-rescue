"""Bundle and launcher fixtures; no real disks, tools installs or EFI operations."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import finish_bundle as bundle


class FinishBundleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.source = self.root / "source"
        (self.source / "kit").mkdir(parents=True)
        (self.source / "finish_install.py").write_text("print('fixture finisher')\n")
        (self.source / "oclp_models.json").write_text(json.dumps({"models": {
            "MacBookPro11,3": {"board_id": "Mac-2BD1B31983FE1663", "name": "Fixture MacBook Pro"},
            "iMac18,2": {"board_id": "Mac-77F17D7DA9285301", "name": "Fixture iMac"},
        }}))
        launcher = Path(__file__).resolve().parent.parent / "kit" / bundle.LAUNCHER
        (self.source / "kit" / bundle.LAUNCHER).write_bytes(launcher.read_bytes())
        self.usb = self.root / "usb"
        self.usb.mkdir()
        self.backup = self.root / "backups"
        self.patch = patch.object(bundle, "BASE", self.source)
        self.patch.start()
        self.addCleanup(self.patch.stop)

    @property
    def folder(self):
        return self.usb / bundle.FOLDER

    def test_bundle_is_self_contained_and_manifest_matches(self):
        result = bundle.install(self.usb, self.backup)
        self.assertEqual(bundle.FOLDER, "OCLP-Finish")
        self.assertEqual(set(result["files"]), {"finish_install.py", "oclp_models.json", bundle.LAUNCHER, "READ-ME-FIRST.txt", "manifest.json"})
        manifest = json.loads((self.folder / "manifest.json").read_text())
        self.assertEqual((manifest["format"], manifest["macos_major"]), (3, 26))
        self.assertNotIn("model", manifest)
        self.assertNotIn("build", manifest)
        for name, digest in manifest["sha256"].items():
            self.assertEqual(hashlib.sha256((self.folder / name).read_bytes()).hexdigest(), digest)
        bundle.verify(self.usb)

    def test_old_model_specific_folder_is_preserved(self):
        old = self.usb / "MBP113-Finish"
        old.mkdir()
        old_script = old / "finish-install.command"
        old_script.write_text("historical snapshot\n")
        bundle.install(self.usb, self.backup)
        self.assertEqual(old_script.read_text(), "historical snapshot\n")
        self.assertEqual(list(old.iterdir()), [old_script])
        bundle.verify(self.usb)

    def test_repeat_keeps_existing_logs_and_creates_no_backups(self):
        bundle.install(self.usb, self.backup)
        log = self.folder / "build" / "bootstrap" / "existing.log"
        log.parent.mkdir(parents=True)
        log.write_text("retain this log\n")
        before = {p.name: p.stat().st_mtime_ns for p in self.folder.iterdir() if p.is_file()}
        result = bundle.install(self.usb, self.backup)
        self.assertEqual(result["changed_files"], [])
        self.assertFalse(self.backup.exists())
        self.assertEqual(log.read_text(), "retain this log\n")
        self.assertEqual(before, {p.name: p.stat().st_mtime_ns for p in self.folder.iterdir() if p.is_file()})

    def test_replacement_backs_up_exact_old_bytes_and_manifest_is_last(self):
        bundle.install(self.usb, self.backup)
        old = (self.folder / "finish_install.py").read_bytes()
        old_manifest = (self.folder / "manifest.json").read_bytes()
        (self.source / "finish_install.py").write_text("print('updated fixture')\n")
        replaced = []
        real_replace = os.replace
        def record_replace(source, dest):
            replaced.append(Path(dest).name)
            return real_replace(source, dest)
        with patch.object(bundle.os, "replace", side_effect=record_replace):
            bundle.install(self.usb, self.backup)
        self.assertEqual((self.backup / "finish_install.py").read_bytes(), old)
        self.assertEqual((self.backup / "manifest.json").read_bytes(), old_manifest)
        self.assertEqual(replaced[-1], "manifest.json")
        bundle.verify(self.usb)

    def test_symlink_destination_is_rejected_before_any_other_write(self):
        self.folder.mkdir()
        elsewhere = self.root / "elsewhere"
        elsewhere.write_text("untouched")
        (self.folder / "manifest.json").symlink_to(elsewhere)
        with self.assertRaisesRegex(ValueError, "symlink"):
            bundle.install(self.usb, self.backup)
        self.assertEqual(elsewhere.read_text(), "untouched")
        self.assertFalse((self.folder / "finish_install.py").exists())
        self.assertFalse(self.backup.exists())

    def test_bundle_folder_and_backup_symlinks_are_rejected(self):
        elsewhere = self.root / "elsewhere"
        elsewhere.mkdir()
        self.folder.symlink_to(elsewhere, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "symlink"):
            bundle.install(self.usb, self.backup)
        self.folder.unlink()
        self.backup.symlink_to(elsewhere, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "symlink"):
            bundle.install(self.usb, self.backup)
        self.assertEqual(list(elsewhere.iterdir()), [])

    def test_backups_inside_usb_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "outside the USB"):
            bundle.install(self.usb, self.usb / "backups")
        self.assertEqual(list(self.usb.iterdir()), [])

    def test_verify_detects_tampering(self):
        bundle.install(self.usb, self.backup)
        (self.folder / "oclp_models.json").write_text("changed model table")
        with self.assertRaisesRegex(ValueError, "outdated"):
            bundle.verify(self.usb)

    def test_launcher_checks_manifest_without_running_finisher(self):
        bundle.install(self.usb, self.backup)
        shell = 'source "$1"; finish_python="$2"; finish_bundle_dir="$3"; verify_finish_bundle'
        args = ["/bin/bash", "-c", shell, "fixture", str(self.folder / bundle.LAUNCHER), sys.executable, str(self.folder)]
        result = subprocess.run(args, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        (self.folder / "finish_install.py").write_text("changed")
        result = subprocess.run(args, capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("did not verify", result.stderr)

    def test_check_without_python_stops_before_setup_or_log_creation(self):
        bundle.install(self.usb, self.backup)
        shell = '''source "$1"
finish_macos_version() { echo 26.7.2; }
finish_darwin_version() { echo 25.7.0; }
find_finish_python() { return 1; }
install_finish_tools() { echo UNEXPECTED-TOOLS-INSTALL; exit 99; }
finish_main --check
'''
        result = subprocess.run(["/bin/bash", "-c", shell, "fixture", str(self.folder / bundle.LAUNCHER)], capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Check mode needs", result.stdout)
        self.assertNotIn("UNEXPECTED", result.stdout)
        self.assertFalse((self.folder / "build").exists())

    def test_wrong_macos_stops_before_python_discovery(self):
        launcher = self.source / "kit" / bundle.LAUNCHER
        shell = '''source "$1"
finish_macos_version() { echo 15.8.1; }
find_finish_python() { echo UNEXPECTED-PYTHON-DISCOVERY; exit 99; }
finish_main --check
'''
        result = subprocess.run(["/bin/bash", "-c", shell, "fixture", str(launcher)], capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("installed macOS Tahoe 26", result.stdout)
        self.assertNotIn("UNEXPECTED", result.stdout)

    def test_audit_forwards_yes_and_check_to_fixture_finisher(self):
        (self.source / "finish_install.py").write_text("import json, sys\nprint(json.dumps(sys.argv[1:]))\n")
        bundle.install(self.usb, self.backup)
        launcher = self.folder / bundle.LAUNCHER
        shell = '''source "$1"
fixture_python="$2"
finish_macos_version() { echo 26.7.2; }
finish_darwin_version() { echo 25.7.0; }
find_finish_python() { printf '%s\\n' "$fixture_python"; }
install_finish_tools() { echo UNEXPECTED-TOOLS-INSTALL; exit 99; }
finish_main --check --yes
'''
        result = subprocess.run(["/bin/bash", "-c", shell, str(self.folder / "fixture-launch"), str(launcher), sys.executable], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(json.loads(result.stdout), ["--check", "--yes"])
        self.assertFalse((self.folder / "build").exists())

    def test_darwin_setup_log_template_produces_unique_filenames(self):
        log_dir = self.root / "fixture-logs"
        log_dir.mkdir()
        template = str(log_dir / "setup-XXXXXXXX")
        names = [subprocess.check_output(["/usr/bin/mktemp", template], text=True).strip() for _ in range(2)]
        self.assertNotEqual(names[0], names[1])
        self.assertTrue(all(Path(name).is_file() for name in names))
        self.assertTrue(all("XXXXXXXX" not in Path(name).name for name in names))

    def test_clt_selection_uses_newest_stable_exact_label_only(self):
        launcher = self.source / "kit" / bundle.LAUNCHER
        listing = '''* Label: macOS Tahoe 26.7.3-25G999
* Label: Command Line Tools for Xcode-26.9
* Label: Command Line Tools for Xcode-26.10
* Label: Command Line Tools for Xcode-27.0 beta
* Label: Command Line Tools for Xcode-27.0 RC
* Label: Command Line Tools for Xcode-27.0 Release Candidate
* Label: Command Line Tools for Xcode-27.0 Preview
'''
        result = subprocess.run(["/bin/bash", "-c", 'source "$1"; select_clt_label', "fixture", str(launcher)], input=listing, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "Command Line Tools for Xcode-26.10")
        result = subprocess.run(["/bin/bash", "-c", 'source "$1"; select_clt_label', "fixture", str(launcher)], input="* Label: macOS Tahoe 26.7.3-25G999\n", capture_output=True, text=True)
        self.assertEqual(result.stdout.strip(), "")


if __name__ == "__main__":
    unittest.main()
