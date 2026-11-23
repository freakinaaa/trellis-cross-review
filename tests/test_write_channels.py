import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


script = Path(__file__).resolve().parents[1] / "scripts/check_write_channels.py"
spec = importlib.util.spec_from_file_location("check_write_channels", script)
checker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checker)


class WriteChannelTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.report = self.root / "channels.json"
        for filename, content in {
            "inventory.log": b"tools: Edit, shell; no plugins, browser, delegation, or hooks",
            "inventory.json": b'["Edit", "shell"]',
            "edit-event.log": b"tool=Edit result=ERROR error=Permission denied",
            "settings.log": b"shell is disabled",
            "before.bin": b"original\x00\r\n", "after.bin": b"original\x00\r\n",
        }.items():
            (self.root / filename).write_bytes(content)
        self.data = {
            "complete": True, "inventory_evidence": "inventory.log",
            "inventory": "inventory.json",
            "checks": {c: {"result": "unavailable", "evidence": "inventory.log"} for c in
                       ("extensions", "browser", "delegation", "hooks")},
        }
        self.data["checks"]["shell"] = {"result": "disabled", "evidence": "settings.log"}
        for c in ("file", "Edit"):
            self.data["checks"][c] = {"result": "denied", "evidence": "edit-event.log",
                                      "before": "before.bin", "after": "after.bin"}

    def check(self):
        self.report.write_text(json.dumps(self.data), encoding="utf-8")
        return checker.check_report(self.report)

    def test_complete_native_inventory_including_extensions(self):
        self.assertEqual(set(self.check()), checker.BASELINE | {"Edit"})

    def test_denied_editor_cannot_mask_unchecked_or_enabled_shell(self):
        del self.data["checks"]["shell"]
        (self.root / "inventory.json").write_text('["Edit"]', encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "missing=.*shell"):
            self.check()
        for result in ("allowed", "succeeded", "unknown", None):
            with self.subTest(result=result):
                self.data["checks"]["shell"] = {"result": result, "evidence": "settings.log"}
                with self.assertRaisesRegex(ValueError, "shell"):
                    self.check()

    def test_unknown_extension_requires_its_own_evidence(self):
        (self.root / "inventory.json").write_text('["Edit", "shell", "new-plugin:write"]', encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "new-plugin:write"):
            self.check()

    def test_denial_requires_native_event_and_two_independent_unchanged_snapshots(self):
        edit = self.data["checks"]["Edit"]
        (self.root / "after.bin").write_bytes(b"modified")
        with self.assertRaisesRegex(ValueError, "changed"):
            self.check()
        edit["after"] = "before.bin"
        with self.assertRaisesRegex(ValueError, "separate"):
            self.check()
        (self.root / "after.bin").write_bytes((self.root / "before.bin").read_bytes())
        edit["after"] = "after.bin"
        del edit["evidence"]
        with self.assertRaisesRegex(ValueError, "expected fields"):
            self.check()
        edit["evidence"] = "edit-event.log"
        (self.root / "edit-event.log").write_bytes(b"")
        with self.assertRaisesRegex(ValueError, "native evidence"):
            self.check()
        (self.root / "edit-event.log").write_bytes(b"tool=Edit result=ERROR error=Permission denied")
        (self.root / "before.bin").write_bytes(b"")
        (self.root / "after.bin").write_bytes(b"")
        with self.assertRaisesRegex(ValueError, "snapshot is empty"):
            self.check()

    def test_incomplete_empty_and_conflicting_claims_block(self):
        self.data["complete"] = False
        with self.assertRaisesRegex(ValueError, "incomplete"):
            self.check()
        self.data["complete"] = True
        self.data["checks"]["Edit"]["result"] = "disabled"
        with self.assertRaisesRegex(ValueError, "expected fields"):
            self.check()
        (self.root / "inventory.json").write_text("[]", encoding="utf-8")
        self.data["checks"] = {}
        with self.assertRaisesRegex(ValueError, "missing="):
            self.check()

    def test_native_inventory_cannot_be_its_own_evidence(self):
        self.data["inventory_evidence"] = "inventory.json"
        with self.assertRaisesRegex(ValueError, "native evidence"):
            self.check()

    def test_empty_native_export_still_requires_all_baseline_surfaces(self):
        (self.root / "inventory.log").write_bytes(b"native read-only mode disables all tools")
        (self.root / "inventory.json").write_text("[]", encoding="utf-8")
        self.data["checks"] = {c: {"result": "disabled", "evidence": "inventory.log"}
                               for c in checker.BASELINE}
        self.assertEqual(set(self.check()), checker.BASELINE)
        for channel in checker.BASELINE:
            with self.subTest(channel=channel):
                record = self.data["checks"].pop(channel)
                with self.assertRaisesRegex(ValueError, "missing=.*" + channel):
                    self.check()
                self.data["checks"][channel] = record

    def test_cli_status_and_duplicate_json_fields(self):
        self.check()
        argv = [sys.executable, "-B", str(script), str(self.report)]
        self.assertEqual(subprocess.run(argv, cwd=self.root, capture_output=True).returncode, 0)
        raw = self.report.read_text(encoding="utf-8").replace(
            '"result": "denied"', '"result": "allowed", "result": "denied"')
        self.report.write_text(raw, encoding="utf-8")
        completed = subprocess.run(argv, cwd=self.root, capture_output=True)
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn(b"Duplicate JSON key", completed.stderr)


if __name__ == "__main__":
    unittest.main()
