import contextlib
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


script = Path(__file__).resolve().parents[1] / "scripts" / "review.py"
spec = importlib.util.spec_from_file_location("trellis_review_entry", script)
review = importlib.util.module_from_spec(spec)
spec.loader.exec_module(review)


class ReviewEntryTests(unittest.TestCase):
    def setUp(self):
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        user_dir = Path(scratch.name) / "home"
        self.config = user_dir / ".codex" / "cross-review.json"
        self.config.parent.mkdir(parents=True)
        self.config.write_text('{"reviewers":["qoder","agy"],"models":{}}', encoding="utf-8")
        env = patch.dict(os.environ, {"HOME": str(user_dir), "USERPROFILE": str(user_dir)})
        env.start()
        self.addCleanup(env.stop)
        self.task = Path(scratch.name) / ".trellis/tasks/sample"
        self.task.mkdir(parents=True)
        self.metadata = self.task / "task.json"
        self.metadata.write_text('{"status":"in_progress","meta":{"prior":"保留"}}', encoding="utf-8")
        self.brief = self.task / "prd.md"
        self.brief.write_text("核对 A1", encoding="utf-8")
        channel = patch.object(review, "ReviewChannel")
        self.channel = channel.start()
        self.addCleanup(channel.stop)
        self.events = []
        self.channel.return_value.messages.side_effect = lambda: list(self.events)
        self.channel.return_value.send.side_effect = self.save_event
        cli = patch.object(review, "run_cli", return_value={"ok": True, "text": "证据 A1\n结论：通过"})
        self.cli = cli.start()
        self.addCleanup(cli.stop)

    def save_event(self, sender, recipient, req_id, body):
        self.events.append({"kind": "message", "by": sender, "to": recipient,
                            "text": f"reqId={req_id}\n{body}"})

    def invoke(self, stage, *, scope=None, dispatch=False, gate=True, extra=()):
        argv = ["gate"] if gate else []
        argv += ["--task", str(self.task), "--stage", stage]
        if scope is not None:
            argv += ["--scope", scope]
        if dispatch:
            argv += ["--revision", "v1", "--brief-file", str(self.brief)]
        argv.extend(extra)
        output = io.StringIO()
        error = io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(error):
            code = review.main(argv)
        return code, json.loads(output.getvalue() or error.getvalue())

    def test_prompt_once_and_wait_without_reading_materials(self):
        self.brief.unlink()
        self.config.unlink()
        code, decision = self.invoke("plan")
        self.assertEqual(code, 0)
        self.assertEqual(decision["status"], "ask")
        self.assertEqual(decision["options"], ["self", "plan", "acceptance", "both"])
        self.assertEqual(self.invoke("plan")[1]["status"], "awaiting_choice")
        self.assertEqual(self.invoke("acceptance")[1]["status"], "awaiting_choice")
        for gate in (True, False):
            code, decision = self.invoke("plan", dispatch=True, gate=gate)
            self.assertEqual((code, decision["status"]), (2, "awaiting_choice"))
        self.channel.assert_not_called()
        self.cli.assert_not_called()

    def test_first_prompt_at_acceptance_only_offers_remaining_stages(self):
        self.assertEqual(self.invoke("acceptance")[1], {
            "status": "ask", "stage": "acceptance", "options": ["self", "acceptance"]})

    def test_configured_pair_and_models_reach_both_rounds(self):
        settings = {"reviewers": ["agy", "qoder"], "models": {"agy": "Custom model A"}}
        self.config.write_text(json.dumps(settings), encoding="utf-8-sig")
        code, result = self.invoke("plan", scope="plan", dispatch=True)
        self.assertEqual((code, result["status"]), (0, "pass"))
        self.assertEqual([event["to"] for event in self.events[:2]], ["agy", "qoder"])
        for receipts in result["rounds"]:
            self.assertEqual(receipts["agy"]["requested_model"], "Custom model A")
            self.assertIsNone(receipts["qoder"]["requested_model"])

    def test_command_line_pair_and_individual_model_override(self):
        self.config.write_text(json.dumps({"reviewers": ["qoder", "agy"],
                                           "models": {"agy": "keep", "qoder": "replace"}}), encoding="utf-8")
        code, result = self.invoke("plan", scope="both", dispatch=True, extra=[
            "--reviewers", "agy", "qoder", "--model", "qoder=Team model B"])
        self.assertEqual((code, result["status"]), (0, "pass"))
        self.assertEqual([event["to"] for event in self.events[:2]], ["agy", "qoder"])
        for receipts in result["rounds"]:
            self.assertEqual(receipts["agy"]["requested_model"], "keep")
            self.assertEqual(receipts["qoder"]["requested_model"], "Team model B")

    def test_missing_machine_config_never_selects_a_pair_implicitly(self):
        self.config.unlink()
        for extra in ([], ["--model", "agy=example"], ["--reviewers", "qoder", "agy"]):
            with self.subTest(extra=extra):
                code, report = self.invoke("plan", scope="both", dispatch=True, extra=extra)
                self.assertEqual((code, report["status"]), (2, "pending"))
                self.assertIn(str(self.config), report["error"])
                self.assertIn("reviewers", report["error"])
        self.channel.assert_not_called()
        self.cli.assert_not_called()

    def test_fully_explicit_cli_works_without_a_config_file(self):
        self.config.unlink()
        code, report = self.invoke("plan", scope="both", dispatch=True, extra=[
            "--reviewers", "qoder", "agy", "--model", "agy=A", "--model", "qoder=B"])
        self.assertEqual((code, report["status"]), (0, "pass"))
        for receipts in report["rounds"]:
            self.assertEqual(receipts["agy"]["requested_model"], "A")
            self.assertEqual(receipts["qoder"]["requested_model"], "B")

    def test_invalid_config_reports_its_path_before_channel_or_dispatch(self):
        for text in ["{", "[]", "{}", '{"reviewers":["qoder","missing"],"models":{}}',
                     '{"reviewers":["qoder","qoder"],"models":{}}',
                     '{"reviewers":[{}, "agy"],"models":{}}',
                     '{"reviewers":["qoder","agy"],"models":{"agy":" "}}',
                     '{"reviewers":["qoder","agy"],"models":{"other":"a"}}']:
            with self.subTest(text=text):
                self.config.write_text(text, encoding="utf-8")
                code, report = self.invoke("plan", scope="both", dispatch=True)
                self.assertEqual((code, report["status"]), (2, "pending"))
                self.assertIn(str(self.config), report["error"])
        self.channel.assert_not_called()
        self.cli.assert_not_called()

    def test_each_scope_routes_only_the_selected_stages(self):
        for scope, stages in [("plan", ["plan"]), ("acceptance", ["acceptance"]),
                              ("both", ["plan", "acceptance"]), ("self", [])]:
            with self.subTest(scope=scope):
                self.events.clear()
                self.channel.reset_mock()
                self.cli.reset_mock()
                self.invoke("plan", scope=scope)
                for stage in ("plan", "acceptance"):
                    before = self.cli.call_count
                    code, result = self.invoke(stage, dispatch=True)
                    if stage in stages:
                        self.assertEqual((code, result["status"]), (0, "pass"))
                        self.assertEqual(self.cli.call_count - before, 4)
                    else:
                        self.assertEqual((code, result["status"]), (2, "self_check"))
                        self.assertEqual(self.cli.call_count, before)
                self.assertEqual(self.channel.call_count, len(stages))
                state = json.loads(self.metadata.read_text(encoding="utf-8"))
                self.assertEqual(state, {"status": "in_progress", "meta": {
                    "prior": "保留", "crossReviewScope": scope}})

    def test_explicit_answer_and_later_change_take_precedence_on_resume(self):
        self.assertEqual(self.invoke("plan")[1]["status"], "ask")
        self.assertEqual(self.invoke("plan", scope="both")[1]["status"], "selected")
        self.assertEqual(self.invoke("acceptance")[1]["status"], "selected")
        self.assertEqual(self.invoke("acceptance", scope="self")[1]["status"], "self_check")
        self.assertEqual(self.invoke("acceptance", gate=False, dispatch=True)[1]["status"], "self_check")
        self.channel.assert_not_called()
        self.cli.assert_not_called()

    def test_legacy_explicit_dispatch_with_no_stage_choice(self):
        self.assertEqual(self.invoke("plan", gate=False, dispatch=True)[1]["status"], "pass")
        self.assertNotIn("crossReviewScope", json.loads(self.metadata.read_text(encoding="utf-8"))["meta"])

    def test_real_cli_restores_selection_across_processes(self):
        argv = [sys.executable, "-B", str(script), "gate", "--task", str(self.task),
                "--stage", "acceptance"]
        for flags, status in [([], "ask"), ([], "awaiting_choice"), (["--scope", "self"], "self_check"),
                              ([], "self_check"), (["--scope", "acceptance"], "selected")]:
            with self.subTest(flags=flags, status=status):
                result = subprocess.run([*argv, *flags], check=True, capture_output=True,
                                        text=True, encoding="utf-8", cwd=self.task)
                self.assertEqual(json.loads(result.stdout)["status"], status)

    def test_failed_metadata_write_preserves_prior_choice(self):
        self.invoke("plan", scope="self")
        original = self.metadata.read_bytes()
        with patch.object(review.os, "replace", side_effect=OSError("busy")):
            with contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
                code = review.main(["gate", "--task", str(self.task), "--stage", "plan",
                                    "--scope", "both", "--revision", "v1", "--brief-file", str(self.brief)])
        self.assertEqual(code, 2)
        self.assertEqual(self.metadata.read_bytes(), original)
        self.assertEqual(list(self.task.glob(".task.json.*.tmp")), [])
        self.channel.assert_not_called()
        self.cli.assert_not_called()


if __name__ == "__main__":
    unittest.main()
