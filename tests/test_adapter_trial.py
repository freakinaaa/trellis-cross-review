import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


class AdapterTrialTests(unittest.TestCase):
    def setUp(self):
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.home = Path(scratch.name) / "fixture home"
        self.install = self.home / ".codex/skills/trellis-cross-review"
        self.config = self.home / ".codex/cross-review.json"
        self.env = {**os.environ, "HOME": str(self.home), "USERPROFILE": str(self.home)}
        source = Path(__file__).resolve().parents[1] / "scripts"
        scripts = self.install / "scripts"
        scripts.mkdir(parents=True)
        for name in ("adapter_trial.py", "review.py"):
            shutil.copyfile(source / name, scripts / name)
        self.git("init", "-q", "-b", "main")
        self.git("add", "scripts")
        self.git("-c", "user.name=Test", "-c", "user.email=test@localhost", "commit", "-qm", "Fixture")

    def command(self, *args, check=True):
        return subprocess.run(args, cwd=self.install, env=self.env, capture_output=True,
                              text=True, encoding="utf-8", check=check)

    def git(self, *args):
        return self.command("git", *args).stdout.strip()

    def trial(self, *reviewers, check=True):
        return self.command(sys.executable, "-B", "scripts/adapter_trial.py",
                            "--reviewers", *reviewers, check=check)

    def test_cancelled_trial_and_retry_preserve_installed_pair(self):
        original = b'{"reviewers":["qoder","agy"],"models":{"agy":"keep"}}\n'
        self.config.write_bytes(original)
        base = self.git("rev-parse", "HEAD")
        first = json.loads(self.trial("agy", "new").stdout)
        tree = Path(first["worktree"])
        config = Path(first["config"])
        self.assertEqual(first["previous_config_sha256"], hashlib.sha256(original).hexdigest())
        self.assertEqual(first["base"], base)
        self.assertFalse(tree.is_relative_to(self.install))
        self.assertFalse(config.is_relative_to(tree))
        self.assertEqual(json.loads(config.read_text(encoding="utf-8")), {
            "reviewers": ["agy", "new"], "models": {},
        })
        self.assertEqual(self.git("-C", str(tree), "branch", "--show-current"), first["branch"])
        self.assertEqual(self.git("-C", str(tree), "rev-parse", "HEAD"), base)

        # The first attempt stops after the author has started editing the adapter.
        draft = tree / "scripts/new_reviewer.py"
        draft.write_text("# partially implemented\n", encoding="utf-8")
        second = json.loads(self.trial("agy", "new").stdout)
        self.assertNotEqual(second["branch"], first["branch"])
        self.assertNotEqual(second["worktree"], first["worktree"])
        self.assertNotEqual(second["config"], first["config"])
        self.assertTrue(draft.is_file())
        self.assertFalse((Path(second["worktree"]) / "scripts/new_reviewer.py").exists())
        self.assertEqual(self.git("branch", "--show-current"), "main")
        self.assertEqual(self.git("rev-parse", "HEAD"), base)
        self.assertEqual(self.git("status", "--porcelain"), "")
        self.assertEqual(self.config.read_bytes(), original)
        result = self.command(sys.executable, "-B", "-c",
                              "import json,runpy; print(json.dumps(runpy.run_path("
                              "'scripts/review.py')['resolve_reviewers'](None, {})))")
        self.assertEqual(json.loads(result.stdout), [["qoder", "agy"], {"agy": "keep"}])

    def test_new_user_can_start_without_creating_home_config(self):
        trial = json.loads(self.trial("first", "second").stdout)
        self.assertIsNone(trial["previous_config_sha256"])
        self.assertTrue(Path(trial["config"]).is_file())
        self.assertFalse(self.config.exists())

    def test_worktree_creation_failure_keeps_original_config_and_partial_trial(self):
        original = b'{"reviewers":["qoder","agy"],"models":{}}'
        self.config.write_bytes(original)
        # Git refuses to create codex/adapter-* while a branch named codex exists.
        self.git("branch", "codex")
        result = self.trial("qoder", "new", check=False)
        self.assertNotEqual(result.returncode, 0)
        trials = self.home / ".codex/cross-review-trials"
        candidate, = trials.glob("*/candidate.json")
        self.assertIn(str(candidate.parent), result.stderr)
        self.assertEqual(json.loads(candidate.read_text(encoding="utf-8"))["reviewers"], ["qoder", "new"])
        self.assertEqual(self.config.read_bytes(), original)
        self.assertEqual(self.git("branch", "--show-current"), "main")
        self.assertEqual(self.git("status", "--porcelain"), "")

    def test_invalid_pair_dirty_or_switched_install_does_not_create_trial(self):
        trials = self.home / ".codex/cross-review-trials"
        self.assertNotEqual(self.trial("same", "same", check=False).returncode, 0)
        draft = self.install / "draft"
        draft.write_text("untracked", encoding="utf-8")
        self.assertNotEqual(self.trial("one", "two", check=False).returncode, 0)
        self.assertEqual(draft.read_text(encoding="utf-8"), "untracked")
        draft.unlink()
        self.git("switch", "-qc", "existing-work")
        self.assertNotEqual(self.trial("one", "two", check=False).returncode, 0)
        self.assertEqual(self.git("branch", "--show-current"), "existing-work")
        self.assertFalse(self.config.exists())
        self.assertFalse(trials.exists())


if __name__ == "__main__":
    unittest.main()
