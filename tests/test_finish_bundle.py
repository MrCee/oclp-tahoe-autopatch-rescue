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
        self.assertEqual(set(result["files"]), {"finish_install.py", bundle.LAUNCHER, "READ-ME-FIRST.txt", "manifest.json"})
        manifest = json.loads((self.folder / "manifest.json").read_text())
        self.assertEqual((manifest["format"], manifest["model"], manifest["macos_major"]), (2, "MacBookPro11,3", 26))
        self.assertNotIn("build", manifest)
        for name, digest in manifest["sha256"].items():
            self.assertEqual(hashlib.sha256((self.folder / name).read_bytes()).hexdigest(), digest)
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
        (self.folder / "finish_install.py").write_text("changed")
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
finish_machine_model() { echo MacBookPro11,3; }
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

    def test_wrong_host_stops_before_python_discovery(self):
        launcher = self.source / "kit" / bundle.LAUNCHER
        shell = '''source "$1"
finish_machine_model() { echo iMac18,2; }
find_finish_python() { echo UNEXPECTED-PYTHON-DISCOVERY; exit 99; }
finish_main --check
'''
        result = subprocess.run(["/bin/bash", "-c", shell, "fixture", str(launcher)], capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("not the preparation Mac", result.stdout)
        self.assertNotIn("UNEXPECTED", result.stdout)

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
