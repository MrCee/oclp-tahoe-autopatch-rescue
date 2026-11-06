"""Internal EFI fixtures only: never mount, inspect or write a real disk."""
import contextlib
import copy
import io
import json
from pathlib import Path
import plistlib
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import finish_install as finish

MBP_MODEL = "MacBookPro11,3"
MBP_BOARD = "Mac-2BD1B31983FE1663"
IMAC_MODEL = "iMac18,2"
IMAC_BOARD = "Mac-77F17D7DA9285301"


class FinishTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()
        self.mount = self.base / "efi"
        self.script_dir = self.base / "usb-tools"
        self.script_dir.mkdir()
        self.table = {"models": {MBP_MODEL: {"name": "MacBook Pro (15-inch, Mid 2014)", "board_id": MBP_BOARD},
                                 IMAC_MODEL: {"name": "iMac (Retina 4K, 21.5-inch, 2017)", "board_id": IMAC_BOARD}}}
        (self.script_dir / "oclp_models.json").write_text(json.dumps(self.table))
        self.config = self.mount / "EFI/OC/config.plist"
        self.original = {
            "#Revision": {"Original-Model": MBP_MODEL},
            "PlatformInfo": {"DataHub": {"SystemProductName": "", "BoardProduct": "",
                                          "SystemSerialNumber": "unchanged"},
                             "UpdateDataHub": False, "Automatic": False, "UpdateSMBIOS": False},
            "NVRAM": {"Add": {finish.OCLP_GUID: {"OCLP-Model": MBP_MODEL},
                                "other-guid": {"boot-args": "-v -x unrelated"}},
                       "Delete": {"other-guid": ["unrelated-variable"]}},
            "ACPI": {"Add": [{"Enabled": True, "Path": "Test.aml"}]},
            "UEFI": {"Drivers": [{"Enabled": True, "Path": "Test.efi"}]},
            "Kernel": {"Add": [{"Enabled": True, "BundlePath": "Test.kext",
                                  "PlistPath": "Contents/Info.plist",
                                  "ExecutablePath": "Contents/MacOS/Test"},
                                 {"Enabled": False, "BundlePath": "Missing.kext"}]},
            "Misc": {"Security": {"SecureBootModel": "Disabled"}},
        }
        self.write_config(self.original)
        for relative in ("EFI/OC/OpenCore.efi", "System/Library/CoreServices/boot.efi",
                         "EFI/OC/ACPI/Test.aml", "EFI/OC/Drivers/Test.efi",
                         "EFI/OC/Kexts/Test.kext/Contents/Info.plist",
                         "EFI/OC/Kexts/Test.kext/Contents/MacOS/Test"):
            path = self.mount / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"fixture boot file")
        self.root = {"Internal": True, "FilesystemType": "apfs", "MountPoint": "/",
                     "SystemImage": False, "APFSVolumeGroupID": "installed-volume-group",
                     "DeviceIdentifier": "disk9s4s1", "APFSSnapshot": True,
                     "APFSContainerReference": "disk9",
                     "APFSPhysicalStores": [{"APFSPhysicalStore": "disk42s2"}]}
        self.container = {"ContainerReference": "disk9",
                          "PhysicalStores": [{"DeviceIdentifier": "disk42s2"}],
                          "Volumes": [{"DeviceIdentifier": "disk9s4", "Roles": ["System"]}]}
        self.store = {"Internal": True, "Content": "Apple_APFS", "DiskUUID": "store-uuid",
                      "DeviceIdentifier": "disk42s2", "ParentWholeDisk": "disk42"}
        self.whole = {"Internal": True, "WholeDisk": True, "VirtualOrPhysical": "Physical",
                      "Content": "GUID_partition_scheme", "DeviceIdentifier": "disk42"}
        self.efi = {"Internal": True, "Content": "EFI", "DiskUUID": "efi-uuid",
                    "DeviceIdentifier": "disk42s1", "ParentWholeDisk": "disk42",
                    "WritableVolume": True}
        self.partitions = [{"DeviceIdentifier": "disk42s1", "Content": "EFI"},
                           {"DeviceIdentifier": "disk42s2", "Content": "Apple_APFS"}]
        self.mounted = True
        self.model, self.version, self.kernel = MBP_MODEL, "26.7.2", "25.6.0"
        self.oem_model = None
        self.build = "25G332"
        self.commands = []
        self.stdout = io.StringIO()
        stack = contextlib.ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(patch.object(finish, "BASE", self.script_dir))
        stack.enter_context(patch.object(finish, "output", side_effect=self.output))
        stack.enter_context(patch.object(finish.subprocess, "run", side_effect=self.run_command))
        stack.enter_context(patch.object(finish.os, "geteuid", return_value=0))
        stack.enter_context(patch.object(finish.os.path, "ismount", side_effect=self.ismount))
        stack.enter_context(contextlib.redirect_stdout(self.stdout))

    def ismount(self, path):
        return Path(path) == self.mount and self.mounted

    def write_config(self, config):
        self.config.parent.mkdir(parents=True, exist_ok=True)
        self.config.write_bytes(plistlib.dumps(config))

    def output(self, command):
        fixed = {("/usr/sbin/sysctl", "-n", "hw.model"): self.model,
                 ("/usr/bin/sw_vers", "-productVersion"): self.version,
                 ("/usr/bin/sw_vers", "-buildVersion"): self.build,
                 ("/usr/bin/uname", "-r"): self.kernel}
        if tuple(command) in fixed:
            return (fixed[tuple(command)] + "\n").encode()
        if command == ["/usr/sbin/nvram", finish.OCLP_GUID + ":oem-product"]:
            if self.oem_model is None:
                raise subprocess.CalledProcessError(1, command, output=b"Error getting variable: data was not found")
            return (finish.OCLP_GUID + ":oem-product\t" + self.oem_model + "\n").encode()
        if command[:3] == ["/usr/sbin/diskutil", "info", "-plist"]:
            records = {"/": self.root, "disk42": self.whole, "disk42s2": self.store,
                       "disk42s1": self.efi}
            info = copy.deepcopy(records[command[3]])
            if command[3] == "disk42s1" and self.mounted:
                info["MountPoint"] = str(self.mount)
            return plistlib.dumps(info)
        if command == ["/usr/sbin/diskutil", "apfs", "list", "-plist"]:
            return plistlib.dumps({"Containers": [self.container]})
        if command == ["/usr/sbin/diskutil", "list", "-plist", "disk42"]:
            return plistlib.dumps({"AllDisksAndPartitions": [{"DeviceIdentifier": "disk42",
                                                              "Partitions": self.partitions}]})
        raise AssertionError("Unexpected command: " + repr(command))

    def run_command(self, command, **kwargs):
        self.commands.append(command)
        if command[:2] == ["/usr/sbin/diskutil", "mount"]:
            self.mounted = True
        elif command == ["/usr/sbin/diskutil", "unmount", "disk42s1"]:
            self.mounted = False
        else:
            raise AssertionError("Unexpected mutation: " + repr(command))

    def reports(self):
        return list(self.script_dir.glob("build/internal-efi/*/report.json"))

    def test_snapshot_resolves_physical_disk_and_changes_only_three_fields(self):
        before = self.config.read_bytes()
        finish.main(["--yes"])
        expected = copy.deepcopy(self.original)
        expected["PlatformInfo"]["DataHub"].update(SystemProductName=MBP_MODEL, BoardProduct=MBP_BOARD)
        expected["PlatformInfo"]["UpdateDataHub"] = True
        self.assertEqual(plistlib.loads(self.config.read_bytes()), expected)
        self.assertEqual(next(self.config.parent.glob("config.before-finish-install-*.plist")).read_bytes(), before)
        self.assertEqual(next(self.script_dir.glob("build/internal-efi/*/config.before.plist")).read_bytes(), before)
        report = json.loads(self.reports()[0].read_text())
        self.assertEqual(report["efi_device"], "disk42s1")
        self.assertEqual(report["system_identity"]["system_volume"], "disk9s4")
        self.assertEqual(report["status"], "configuration-verified-awaiting-boot-test")
        self.assertTrue(report["changed"])
        self.assertFalse(report["usb_free_boot_verified"])
        self.assertEqual(self.commands, [])

    def test_second_model_uses_its_own_target_name_and_board(self):
        self.model = IMAC_MODEL
        self.original["#Revision"]["Original-Model"] = IMAC_MODEL
        self.original["NVRAM"]["Add"][finish.OCLP_GUID]["OCLP-Model"] = IMAC_MODEL
        self.write_config(self.original)
        finish.main(["--yes"])
        updated = plistlib.loads(self.config.read_bytes())
        self.assertEqual(updated["PlatformInfo"]["DataHub"]["SystemProductName"], IMAC_MODEL)
        self.assertEqual(updated["PlatformInfo"]["DataHub"]["BoardProduct"], IMAC_BOARD)
        text = self.stdout.getvalue()
        self.assertIn("Detected Mac: iMac (Retina 4K, 21.5-inch, 2017) (iMac18,2)", text)
        self.assertIn("Installed OpenCore target: iMac (Retina 4K, 21.5-inch, 2017) (iMac18,2)", text)
        self.assertIn(IMAC_BOARD, text)

    def test_unknown_host_and_unknown_internal_target_stop_without_writes(self):
        self.model = "Unknown999,1"
        with self.assertRaisesRegex(finish.FinishError, "Unknown Mac model"):
            finish.main(["--yes"])
        self.model = MBP_MODEL
        self.original["NVRAM"]["Add"][finish.OCLP_GUID]["OCLP-Model"] = "Unknown999,1"
        self.original["#Revision"]["Original-Model"] = "Unknown999,1"
        self.write_config(self.original)
        with self.assertRaisesRegex(finish.FinishError, "Unknown Mac model"):
            finish.main(["--yes"])
        self.assertEqual(self.reports(), [])
        self.assertEqual(self.commands, [])

    def test_missing_and_invalid_model_table_stop_before_mounts(self):
        table_path = self.script_dir / "oclp_models.json"
        table_path.unlink()
        with self.assertRaisesRegex(finish.FinishError, "model table could not be read"):
            finish.main(["--yes"])
        table = copy.deepcopy(self.table)
        table["models"][MBP_MODEL]["board_id"] = "not-a-board-id"
        table_path.write_text(json.dumps(table))
        with self.assertRaisesRegex(finish.FinishError, "Invalid model or board-ID"):
            finish.main(["--yes"])
        self.assertEqual(self.commands, [])
        self.assertEqual(self.reports(), [])

    def test_oem_hint_with_percent_encoded_nul_is_used_and_disagreement_is_refused(self):
        self.oem_model = MBP_MODEL + "%00"
        host = finish.validate_host()
        self.assertEqual(host["model"], MBP_MODEL)
        self.assertEqual(host["model_source"], "OCLP oem-product NVRAM")
        self.model = IMAC_MODEL
        with self.assertRaisesRegex(finish.FinishError, "disagrees with OCLP's original model"):
            finish.main(["--yes"])
        self.assertEqual(self.commands, [])

    def test_malformed_oem_hint_and_nvram_read_failure_stop(self):
        for hint in ("MacBookPro11,3%ZZ", "MacBookPro11,3%00garbage", "%FF", "bad-model"):
            self.oem_model = hint
            with self.assertRaisesRegex(finish.FinishError, "Malformed original-model"):
                finish.main(["--yes"])
        original_output = self.output

        def denied(command):
            if command[0] == "/usr/sbin/nvram":
                raise subprocess.CalledProcessError(1, command, output=b"not permitted")
            return original_output(command)

        with patch.object(finish, "output", side_effect=denied):
            with self.assertRaisesRegex(finish.FinishError, "Could not read OCLP's original-model"):
                finish.main(["--yes"])
        self.assertEqual(self.commands, [])

    def test_default_confirmation_accepts_detected_model_or_stops_to_change_target(self):
        before = self.config.read_bytes()
        with patch.object(finish.sys.stdin, "isatty", return_value=True), \
                patch("builtins.input", return_value="c"):
            with self.assertRaisesRegex(finish.FinishError, "Settings → Target Model"):
                finish.main([])
        self.assertEqual(self.config.read_bytes(), before)
        self.assertEqual(self.reports(), [])
        with patch.object(finish.sys.stdin, "isatty", return_value=True), \
                patch("builtins.input", return_value="u"):
            finish.main([])
        self.assertEqual(plistlib.loads(self.config.read_bytes())["PlatformInfo"]["DataHub"]["BoardProduct"], MBP_BOARD)

    def test_noninteractive_changes_need_yes_but_check_and_already_correct_never_prompt(self):
        with patch.object(finish.sys.stdin, "isatty", return_value=False):
            with self.assertRaisesRegex(finish.FinishError, "interactive Terminal"):
                finish.main([])
        with patch("builtins.input", side_effect=AssertionError("unexpected prompt")):
            with self.assertRaisesRegex(finish.FinishError, "needs the DataHub fix"):
                finish.main(["--check"])
            self.write_config(finish.corrected_config(self.original, self.model))
            before = self.config.read_bytes()
            finish.main([])
            self.assertEqual(self.config.read_bytes(), before)
            self.assertEqual(self.reports(), [])

    def test_inconsistent_on_disk_oclp_metadata_is_refused(self):
        self.original["#Revision"]["Original-Model"] = IMAC_MODEL
        self.write_config(self.original)
        with self.assertRaisesRegex(finish.FinishError, "inconsistent OCLP model metadata"):
            finish.main(["--yes"])
        self.assertEqual(self.reports(), [])

    def test_nonsnapshot_system_and_container_store_fallback(self):
        self.root["DeviceIdentifier"] = "disk9s4"
        self.root["APFSSnapshot"] = False
        del self.root["APFSPhysicalStores"]
        self.assertEqual(finish.internal_efi()["DeviceIdentifier"], "disk42s1")

    def test_wrong_macos_or_darwin_stops_before_mounts_and_reports(self):
        for field, value in (("version", "15.7"), ("kernel", "24.6.0")):
            saved = getattr(self, field)
            setattr(self, field, value)
            with self.assertRaisesRegex(finish.FinishError, "installed macOS Tahoe desktop"):
                finish.main(["--yes"])
            setattr(self, field, saved)
        self.assertEqual(self.commands, [])
        self.assertEqual(self.reports(), [])
        self.assertEqual(plistlib.loads(self.config.read_bytes()), self.original)

    def test_recovery_external_and_unidentified_system_are_refused(self):
        for changes in ({"SystemImage": True}, {"Internal": False}, {"APFSVolumeGroupID": ""},
                        {"FilesystemType": "hfs"}, {"MountPoint": "/Volumes/Installed"}):
            original = dict(self.root)
            self.root.update(changes)
            with self.assertRaisesRegex(finish.FinishError, "installed system"):
                finish.main(["--yes"])
            self.root = original
        self.container["Volumes"][0]["Roles"] = ["Recovery"]
        with self.assertRaisesRegex(finish.FinishError, "APFS System volume"):
            finish.main(["--yes"])
        self.assertEqual(self.reports(), [])

    def test_multistore_and_disagreeing_store_are_refused(self):
        self.container["PhysicalStores"].append({"DeviceIdentifier": "disk43s2"})
        with self.assertRaisesRegex(finish.FinishError, "exactly one APFS physical store"):
            finish.main(["--yes"])
        self.container["PhysicalStores"].pop()
        self.root["APFSPhysicalStores"][0]["APFSPhysicalStore"] = "disk43s2"
        with self.assertRaisesRegex(finish.FinishError, "identities disagree"):
            finish.main(["--yes"])
        self.assertEqual(self.commands, [])

    def test_nonphysical_or_non_guid_disk_is_refused(self):
        for changes in ({"Internal": False}, {"VirtualOrPhysical": "Virtual"},
                        {"Content": "FDisk_partition_scheme"}, {"WholeDisk": False}):
            original = dict(self.whole)
            self.whole.update(changes)
            with self.assertRaisesRegex(finish.FinishError, "internal physical disk"):
                finish.main(["--yes"])
            self.whole = original

    def test_efi_identity_and_ambiguity_are_refused(self):
        for changes in ({"Internal": False}, {"ParentWholeDisk": "disk43"}, {"DiskUUID": ""}):
            original = dict(self.efi)
            self.efi.update(changes)
            with self.assertRaisesRegex(finish.FinishError, "exactly one verified EFI"):
                finish.main(["--yes"])
            self.efi = original
        self.partitions.append(dict(self.partitions[0]))
        with self.assertRaisesRegex(finish.FinishError, "exactly one verified EFI"):
            finish.main(["--yes"])

    def test_wrong_oclp_target_is_refused(self):
        self.original["NVRAM"]["Add"][finish.OCLP_GUID]["OCLP-Model"] = "iMac18,2"
        self.original["#Revision"]["Original-Model"] = "iMac18,2"
        self.write_config(self.original)
        with self.assertRaisesRegex(finish.FinishError, "does not match detected Mac"):
            finish.main(["--yes"])
        self.assertEqual(self.reports(), [])

    def test_conflicting_datahub_values_are_preserved(self):
        for key in ("SystemProductName", "BoardProduct"):
            config = copy.deepcopy(self.original)
            config["PlatformInfo"]["DataHub"][key] = "other-model"
            self.write_config(config)
            before = self.config.read_bytes()
            with self.assertRaisesRegex(finish.FinishError, "Conflicting DataHub"):
                finish.main(["--yes"])
            self.assertEqual(self.config.read_bytes(), before)
        self.assertEqual(self.reports(), [])

    def test_automatic_or_spoofed_configs_are_preserved(self):
        for values in ({"Automatic": True}, {"UpdateSMBIOS": True},
                       {"Generic": {"SystemProductName": "MacBookPro14,3"}}):
            config = copy.deepcopy(self.original)
            config["PlatformInfo"].update(values)
            self.write_config(config)
            with self.assertRaisesRegex(finish.FinishError, "automatic or spoofed"):
                finish.main(["--yes"])
            self.assertEqual(plistlib.loads(self.config.read_bytes()), config)

    def test_check_prints_actual_blank_values_and_writes_nothing(self):
        before = self.config.read_bytes()
        with self.assertRaisesRegex(finish.FinishError, "needs the DataHub fix"):
            finish.main(["--check"])
        text = self.stdout.getvalue()
        self.assertIn("Internal EFI: disk42s1", text)
        self.assertIn(str(self.config), text)
        self.assertIn("DataHub/SystemProductName: ''", text)
        self.assertIn("DataHub/BoardProduct: ''", text)
        self.assertIn("PlatformInfo/UpdateDataHub: False", text)
        self.assertEqual(self.config.read_bytes(), before)
        self.assertEqual(self.reports(), [])
        self.assertEqual(list(self.config.parent.glob("config.before-*.plist")), [])
        self.assertEqual(self.commands, [])

    def test_check_succeeds_readonly_without_reports(self):
        self.write_config(finish.corrected_config(self.original, self.model))
        self.efi["WritableVolume"] = False
        finish.main(["--check"])
        self.assertIn("PASS:", self.stdout.getvalue())
        self.assertEqual(self.reports(), [])

    def test_unmounted_check_mounts_readonly_and_cleans_up_on_failure(self):
        self.mounted = False
        with self.assertRaisesRegex(finish.FinishError, "needs the DataHub fix"):
            finish.main(["--check"])
        self.assertEqual(self.commands, [["/usr/sbin/diskutil", "mount", "readOnly", "disk42s1"],
                                         ["/usr/sbin/diskutil", "unmount", "disk42s1"]])
        self.assertFalse(self.mounted)
        self.assertEqual(self.reports(), [])

    def test_unmounted_write_cleans_up_after_success(self):
        self.mounted = False
        finish.main(["--yes"])
        self.assertEqual(self.commands, [["/usr/sbin/diskutil", "mount", "disk42s1"],
                                         ["/usr/sbin/diskutil", "unmount", "disk42s1"]])
        self.assertFalse(self.mounted)

    def test_existing_readonly_mount_is_not_forcibly_remounted(self):
        self.efi["WritableVolume"] = False
        with self.assertRaisesRegex(finish.FinishError, "read-only"):
            finish.main(["--yes"])
        self.assertEqual(self.commands, [])
        self.assertEqual(self.reports(), [])

    def test_repeat_preserves_config_bytes_and_creates_no_second_efi_backup(self):
        finish.main(["--yes"])
        before = self.config.read_bytes()
        finish.main(["--yes"])
        self.assertEqual(self.config.read_bytes(), before)
        self.assertEqual(len(list(self.config.parent.glob("config.before-finish-install-*.plist"))), 1)
        reports = [json.loads(p.read_text()) for p in self.reports()]
        self.assertEqual([r["changed"] for r in reports], [True])

    def test_missing_opencore_gives_internal_install_guidance(self):
        self.config.unlink()
        with self.assertRaisesRegex(finish.FinishError, "INTERNAL drive's EFI"):
            finish.main(["--check"])
        self.assertEqual(self.reports(), [])

    def test_uefi_bootstrap_is_accepted_and_missing_bootstrap_refused(self):
        (self.mount / "System/Library/CoreServices/boot.efi").unlink()
        with self.assertRaisesRegex(finish.FinishError, "bootstrap is missing"):
            finish.main(["--yes"])
        bootstrap = self.mount / "EFI/BOOT/BOOTx64.efi"
        bootstrap.parent.mkdir(parents=True)
        bootstrap.write_bytes(b"fixture UEFI bootstrap")
        finish.main(["--yes"])
        self.assertEqual(json.loads(self.reports()[0].read_text())["boot_layout"], "UEFI")

    def test_missing_enabled_file_is_refused_before_efi_backup(self):
        (self.mount / "EFI/OC/Drivers/Test.efi").unlink()
        with self.assertRaisesRegex(finish.FinishError, "Missing or empty enabled"):
            finish.main(["--yes"])
        self.assertEqual(self.reports(), [])
        self.assertEqual(plistlib.loads(self.config.read_bytes()), self.original)

    def test_traversing_and_symlinked_enabled_paths_are_refused(self):
        config = copy.deepcopy(self.original)
        config["UEFI"]["Drivers"][0]["Path"] = "../../outside.efi"
        self.write_config(config)
        with self.assertRaisesRegex(finish.FinishError, "traversing"):
            finish.main(["--yes"])
        self.write_config(self.original)
        driver = self.mount / "EFI/OC/Drivers/Test.efi"
        driver.unlink()
        driver.symlink_to(self.mount / "EFI/OC/OpenCore.efi")
        with self.assertRaisesRegex(finish.FinishError, "symlinked"):
            finish.main(["--yes"])

    def test_symlinked_config_and_usb_log_directory_are_refused(self):
        saved = self.base / "elsewhere.plist"
        self.config.rename(saved)
        self.config.symlink_to(saved)
        with self.assertRaisesRegex(finish.FinishError, "symlinked"):
            finish.main(["--yes"])
        self.config.unlink()
        saved.rename(self.config)
        (self.script_dir / "build").symlink_to(self.base, target_is_directory=True)
        with self.assertRaisesRegex(finish.FinishError, "symlinked"):
            finish.main(["--yes"])
        self.assertEqual(plistlib.loads(self.config.read_bytes()), self.original)

    def test_changed_system_identity_aborts_before_efi_write_and_records_error(self):
        initial = finish.internal_efi()
        changed = copy.deepcopy(initial)
        changed["SystemIdentity"]["physical_store_uuid"] = "replacement-drive"
        with patch.object(finish, "internal_efi", side_effect=[initial, changed]):
            with self.assertRaisesRegex(finish.FinishError, "identity changed"):
                finish.main(["--yes"])
        self.assertEqual(plistlib.loads(self.config.read_bytes()), self.original)
        self.assertEqual(list(self.config.parent.glob("config.before-*.plist")), [])
        self.assertEqual(json.loads(self.reports()[0].read_text())["status"], "incomplete")

    def test_concurrent_config_edit_is_never_overwritten(self):
        host = finish.validate_host()
        changed = copy.deepcopy(self.original)
        changed["Misc"]["new-setting"] = "external edit"

        calls = 0

        def validator():
            nonlocal calls
            calls += 1
            if calls == 2:
                self.write_config(changed)
            return host

        with patch.object(finish, "validate_host", side_effect=validator):
            with self.assertRaisesRegex(finish.FinishError, "config changed"):
                finish.main(["--yes"])
        self.assertEqual(plistlib.loads(self.config.read_bytes()), changed)
        self.assertEqual(list(self.config.parent.glob("config.before-*.plist")), [])

    def test_direct_nonroot_run_reexecutes_same_standalone_script_with_sudo(self):
        with patch.object(finish.os, "geteuid", return_value=501), \
                patch.object(finish.os, "execv", side_effect=RuntimeError("exec sentinel")) as execute:
            with self.assertRaisesRegex(RuntimeError, "exec sentinel"):
                finish.main(["--check"])
        command = execute.call_args.args
        self.assertEqual(command[0], "/usr/bin/sudo")
        self.assertEqual(command[1][-1], "--check")
        self.assertIn(str(Path(finish.__file__).resolve()), command[1])
        self.assertEqual(self.commands, [])


if __name__ == "__main__":
    unittest.main()
