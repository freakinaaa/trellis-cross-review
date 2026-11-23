"""Regression tests for reviewer process receipts and verdict markers."""
import importlib.util
import json
import unittest
from pathlib import Path
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "review.py"
spec = importlib.util.spec_from_file_location("trellis_review", SCRIPT)
review = importlib.util.module_from_spec(spec)
spec.loader.exec_module(review)


class ProviderReceiptTests(unittest.TestCase):
    body = "检查已完成。\n结论：通过\n"
    missing = "File not found: 旧版设计.md"

    def provider_events(self):
        yield (
            review.Qoder,
            {"type": "user", "message": {"content": [
                {"type": "tool_result", "is_error": True, "content": self.missing},
            ]}},
            {"type": "result", "subtype": "success", "is_error": False, "result": self.body},
            {"type": "result", "subtype": "error", "is_error": True, "error": "upstream EOF"},
        )
        yield (
            review.Antigravity,
            {"event": "step_update", "step_update": {
                "state": "ERROR", "step_type": "tool", "tool_name": "read_file",
                "tool_info": {"error": {"message": self.missing}},
            }},
            {"event": "result", "result": {"status": "SUCCESS", "response": self.body}},
            {"event": "result", "result": {"status": "ERROR", "error": "upstream EOF"}},
        )

    @staticmethod
    def decode(provider, events, code=0, stderr=""):
        stream = "\n".join(json.dumps(event, ensure_ascii=False) for event in events)
        return review._decode_provider(provider, code, stream, stderr)

    def test_read_error_before_success_is_a_warning(self):
        for provider, tool_error, success, _ in self.provider_events():
            with self.subTest(provider=provider.__name__):
                receipt = self.decode(provider, [tool_error, success])
                self.assertTrue(receipt["ok"], receipt)
                self.assertEqual(receipt["warnings"], [self.missing])
                self.assertEqual(receipt["error"], "")
                self.assertEqual(receipt["text"], self.body)

    def test_read_denial_echo_and_separate_auth_failure(self):
        self.missing = "permission denied: archived.md"
        echoed = "[warning] " + self.missing
        for provider, tool_error, success, _ in self.provider_events():
            with self.subTest(provider=provider.__name__):
                if provider is review.Qoder:
                    tool_error["message"]["content"][0]["content"] = [{"type": "text", "text": self.missing}]
                receipt = self.decode(provider, [tool_error, success], stderr=echoed)
                self.assertTrue(receipt["ok"], receipt)
                self.assertEqual(receipt["warnings"], [self.missing])
                failed = self.decode(provider, [tool_error, success], stderr=echoed + "\nauthentication required")
                self.assertFalse(failed["ok"])
                self.assertIn("authentication required", failed["error"])

    def test_denied_command_is_a_hard_failure(self):
        self.missing = "auto-denied by policy"
        for provider, tool_error, success, _ in self.provider_events():
            events = []
            if provider is review.Qoder:
                events.append({"type": "assistant", "message": {"content": [
                    {"type": "tool_use", "id": "command-1", "name": "Bash"}]}})
                tool_error["message"]["content"][0]["tool_use_id"] = "command-1"
            else:
                tool_error["step_update"]["tool_name"] = "run_command"
            with self.subTest(provider=provider.__name__):
                receipt = self.decode(provider, events + [tool_error, success])
                self.assertFalse(receipt["ok"])
                self.assertIn(self.missing, receipt["error"])

    def test_success_with_tool_eof_does_not_retry(self):
        self.missing = "EOF reading old file"
        for provider, tool_error, success, _ in self.provider_events():
            name = "qoder" if provider is review.Qoder else "agy"
            stream = "\n".join(json.dumps(e) for e in (tool_error, success))
            with self.subTest(name=name), patch.object(provider, "executable", return_value=name), \
                    patch.object(review, "_provider_process", return_value=(0, stream, "")) as process:
                result = review.run_cli(name, "问题", None, SCRIPT.parent, 5)
                self.assertTrue(result["ok"], result)
                self.assertEqual(result["attempts"], 1)
                process.assert_called_once()

    def test_tool_warning_does_not_hide_failed_or_conflicting_terminal(self):
        for provider, tool_error, success, failure in self.provider_events():
            for code, terminals in [(1, [success]), (0, []), (0, [failure]), (0, [failure, success])]:
                with self.subTest(provider=provider.__name__, code=code, terminals=terminals):
                    receipt = self.decode(provider, [tool_error, *terminals], code)
                    self.assertFalse(receipt["ok"])
                    self.assertTrue(receipt["error"])

    def test_empty_success_with_tool_error_is_still_a_failure(self):
        self.body = "  \n"
        for provider, tool_error, success, _ in self.provider_events():
            with self.subTest(provider=provider.__name__):
                receipt = self.decode(provider, [tool_error, success])
                self.assertFalse(receipt["ok"])
                self.assertIn("empty", receipt["error"])

    def test_model_rejection_for_adapter_without_catalog(self):
        class Adapter:
            executable = staticmethod(lambda: "test-cli")
            request = staticmethod(lambda prompt, model, seconds: ([], prompt))
            decode = staticmethod(lambda events: (False, "", None, ["unknown model"], []))

        with patch.dict(review.PROVIDERS, {"test-cli": Adapter}), \
                patch.object(review, "_provider_process", return_value=(1, "", "")) as process:
            result = review.run_cli("test-cli", "review", "retired", SCRIPT.parent, 5)
        self.assertFalse(result["ok"])
        self.assertIn("unknown model", result["error"])
        process.assert_called_once()


class VerdictTests(unittest.TestCase):
    def test_list_fenced_examples_never_supply_the_verdict(self):
        cases = [
            ("- ```\n  结论：通过\n  ```\n结论：阻塞", "block"),
            ("- ```text\n  结论：阻塞\n  ```\n结论：通过", "pass"),
            ("1. ~~~\n   结论：通过\n2. 结论：阻塞", "block"),
            ("- ```\n  结论：通过\n\n结论：阻塞", "block"),
            ("- 示例\n  - 子项\n    ````\n    ```\n    结论：阻塞\n    ````\n    结论：通过", "pass"),
            ("- ```\n      ```\n  结论：通过\n  ```\n结论：阻塞", "block"),
            ("- > ```\n  > 结论：通过\n  > ```\n结论：阻塞", "block"),
            ("-     ```\n      结论：通过\n  结论：阻塞", "block"),
        ]
        for body, expected in cases:
            with self.subTest(body=body):
                self.assertEqual(review.parse_verdict(body), expected)

    def test_narrative_verdict_labels_and_trailing_notes(self):
        for marker, expected in [("通过", "pass"), ("阻塞", "block"), ("待复核", "pending")]:
            with self.subTest(marker=marker):
                raw = f"结论：此处设计偏重\n\n**结论：{marker}**\n备注：详见回执附件。"
                self.assertEqual(review.parse_verdict(raw), expected)
                self.assertEqual(review.parse_verdict(f"结论：{marker}\n结论：此处设计偏重"), expected)

    def test_missing_or_conflicting_markers(self):
        for raw in ["结论：此处设计偏重", "结论：通过\n备注\nVerdict: blocked", "结论：待复核\n结论：通过",
                    "> 结论：阻塞\n```\n结论：通过\n```\n    Verdict: passed"]:
            with self.subTest(raw=raw):
                self.assertEqual(review.parse_verdict(raw), "pending")
        self.assertEqual(review.parse_verdict("> 结论：阻塞\n结论：通过\nVerdict: Passed.\n备注"), "pass")


if __name__ == "__main__":
    unittest.main()
