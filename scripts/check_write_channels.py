"""Check coverage of a native write-channel inventory and its probe artifacts."""
import argparse
import hashlib
import json
import sys
from pathlib import Path


BASELINE = frozenset({"file", "shell", "extensions", "browser", "delegation", "hooks"})


def unique_keys(pairs):
    data = {}
    for key, value in pairs:
        if key in data:
            raise ValueError(f"Duplicate JSON key: {key}")
        data[key] = value
    return data


def artifact(root, name):
    if not isinstance(name, str) or not name.strip() or Path(name).is_absolute():
        raise ValueError("Expected an artifact path relative to the report")
    path = (root / name).resolve(strict=True)
    if not path.is_relative_to(root) or not path.is_file():
        raise ValueError(f"Artifact must be a file inside the evidence directory: {name}")
    return path


def digest(path):
    value = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(65536), b""):
            value.update(chunk)
    return value.digest()


def check_report(report):
    """The adapter author verifies vendor event semantics; this verifies coverage and bytes."""
    report = report.resolve(strict=True)
    data = json.loads(report.read_text(encoding="utf-8-sig"), object_pairs_hook=unique_keys)
    if not isinstance(data, dict) or data.get("complete") is not True:
        raise ValueError("The native channel inventory is incomplete")
    inventory = artifact(report.parent, data.get("inventory"))
    if inventory.samefile(report):
        raise ValueError("Use a separate native inventory export")

    def evidence(name):
        path = artifact(report.parent, name)
        if path.samefile(report) or path.samefile(inventory) or not path.stat().st_size:
            raise ValueError(f"Missing independent native evidence: {name}")
        return path

    evidence(data.get("inventory_evidence"))
    native = json.loads(inventory.read_text(encoding="utf-8-sig"))
    if (not isinstance(native, list)
            or not all(isinstance(c, str) and c.strip() and c.strip() == c for c in native)
            or len(set(native)) != len(native)):
        raise ValueError("Expected an inventory export of distinct native channel names")
    channels = BASELINE.union(native)
    checks = data.get("checks")
    if not isinstance(checks, dict):
        raise ValueError("Expected evidence indexed by channel")
    missing, extra = channels - checks.keys(), checks.keys() - channels
    if missing or extra:
        raise ValueError(f"Inventory mismatch: missing={sorted(missing)}, extra={sorted(extra)}")
    for channel in sorted(channels):
        check = checks[channel]
        if not isinstance(check, dict):
            raise ValueError(f"{channel}: expected a check object")
        result = check.get("result")
        if result not in ("disabled", "unavailable", "denied"):
            raise ValueError(f"{channel}: unverified or writable channel ({result!r})")
        fields = {"result", "evidence"}
        if result == "denied":
            fields.update(("before", "after"))
        if set(check) != fields:
            raise ValueError(f"{channel}: expected fields {sorted(fields)} for {result}")
        event = evidence(check["evidence"])
        if result == "denied":
            before = artifact(report.parent, check["before"])
            after = artifact(report.parent, check["after"])
            if (before.samefile(after) or before.samefile(event) or after.samefile(event)
                    or before.samefile(report) or after.samefile(report)):
                raise ValueError(f"{channel}: supply separate before/after snapshots and native evidence")
            if not before.stat().st_size:
                raise ValueError(f"{channel}: the original probe snapshot is empty")
            if digest(before) != digest(after):
                raise ValueError(f"{channel}: the denied probe changed the file contents")
    return sorted(channels)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path, help="Path to the JSON channel inventory and checks")
    args = parser.parse_args()
    try:
        channels = check_report(args.report)
    except (OSError, ValueError) as exc:
        print(f"Write-channel verification blocked: {exc}", file=sys.stderr)
        return 1
    print("Verified evidence coverage: " + ", ".join(channels))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
