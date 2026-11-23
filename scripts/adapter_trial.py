"""Prepare an isolated checkout and configuration for a candidate reviewer pair."""

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile


def git(repo, *args):
    result = subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True,
        encoding="utf-8", errors="replace",
    )
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or f"Git exited with {result.returncode}")
    return result.stdout.strip()


def start_trial(installation, reviewers):
    if len(reviewers) != 2 or reviewers[0] == reviewers[1] or not all(r.strip() for r in reviewers):
        raise ValueError("请选择两位不同的评审者")
    if Path(git(installation, "rev-parse", "--show-toplevel")).resolve() != installation.resolve():
        raise ValueError("已安装技能须位于独立 Git 仓库的根目录")
    if git(installation, "branch", "--show-current") != "main":
        raise ValueError("请从已安装技能的 main 分支启动试验")
    if git(installation, "status", "--porcelain", "--untracked-files=all"):
        raise ValueError("已安装技能的 main 工作区包含未提交的改动")
    base = git(installation, "rev-parse", "--verify", "refs/heads/main")
    codex = Path.home() / ".codex"
    try:
        previous_config_sha256 = hashlib.sha256((codex / "cross-review.json").read_bytes()).hexdigest()
    except FileNotFoundError:
        previous_config_sha256 = None
    trials = codex / "cross-review-trials"
    if trials.resolve().is_relative_to(installation.resolve()):
        raise ValueError("试验目录须位于已安装技能仓库之外")
    trials.mkdir(parents=True, exist_ok=True)
    trial = Path(tempfile.mkdtemp(prefix="adapter-", dir=trials))
    worktree = trial / "worktree"
    config = trial / "candidate.json"
    branch = "codex/" + trial.name
    try:
        config.write_text(json.dumps({"reviewers": reviewers, "models": {}},
                                     indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        git(installation, "worktree", "add", "-b", branch, str(worktree), base)
    except (OSError, RuntimeError) as exc:
        raise RuntimeError(f"创建试验失败，目录保留在 {trial}：{exc}") from exc
    return {"worktree": str(worktree), "config": str(config), "branch": branch, "base": base,
            "previous_config_sha256": previous_config_sha256}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reviewers", nargs=2, required=True, metavar=("FIRST", "SECOND"))
    args = parser.parse_args()
    try:
        trial = start_trial(Path(__file__).resolve().parents[1], args.reviewers)
    except (OSError, ValueError, RuntimeError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(json.dumps(trial, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    raise SystemExit(main())
