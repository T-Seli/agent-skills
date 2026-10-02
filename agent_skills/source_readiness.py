"""Read-only source readiness checks; never fetch, install, or activate."""
import hashlib
import argparse
import json
import subprocess
from pathlib import Path


def _git(root, *args):
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True,
                          text=True, check=True).stdout.strip()


def source_receipt(root, *, expected_commit=None):
    """Pin a real checkout and its tracked source tree, independent of machine path."""
    root = Path(root).resolve(strict=True)
    if Path(_git(root, "rev-parse", "--show-toplevel")) != root:
        raise ValueError("source root must be the checkout root")
    commit = _git(root, "rev-parse", "HEAD")
    if expected_commit is not None and (not isinstance(expected_commit, str) or len(expected_commit) != 40
                                        or any(c not in "0123456789abcdef" for c in expected_commit)):
        raise ValueError("expected full 40-character commit")
    if expected_commit is not None and commit != expected_commit:
        raise ValueError("source commit mismatch")
    if _git(root, "status", "--porcelain", "--untracked-files=all"):
        raise ValueError("source checkout is dirty")
    required = ("agent_skills/catalog.json", "skills/workflow-contracts/contracts.md",
                "global/CLAUDE.md", "install.sh")
    files = {}
    for name in required:
        path = root / name
        if not path.is_file() or path.is_symlink():
            raise ValueError(f"missing or linked source file: {name}")
        files[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    return {"schema": 1, "commit": commit, "files": files,
            "tree": _git(root, "rev-parse", "HEAD^{tree}"),
            "status": "source-verified", "activation": "not-verified"}


def compare_receipt(root, receipt):
    if not isinstance(receipt, dict) or set(receipt) != {
            "schema", "commit", "files", "tree", "status", "activation"} or receipt["schema"] != 1:
        return {"ready": False, "reason": "invalid-receipt"}
    try:
        observed = source_receipt(root, expected_commit=receipt["commit"])
    except (OSError, subprocess.CalledProcessError, ValueError) as exc:
        return {"ready": False, "reason": str(exc)}
    return {"ready": observed == receipt, "reason": "source-match" if observed == receipt else "source-mismatch"}


def installed_links(root, home):
    """Report host link targets only; a running agent still needs native load proof."""
    root, home = Path(root).resolve(), Path(home)
    targets = {"claude-core": (home / ".claude/CLAUDE.md", root / "global/CLAUDE.md"),
               "claude-skills": (home / ".claude/skills/workflow-contracts", root / "skills/workflow-contracts"),
               "codex-skills": (home / ".agents/skills/workflow-contracts", root / "skills/workflow-contracts")}
    checks = {name: link.is_symlink() and link.resolve() == source
              for name, (link, source) in targets.items()}
    return {"links": checks, "ready": all(checks.values()), "native_load": "unverified"}


def main():
    parser = argparse.ArgumentParser(description="Read-only source and adapter readiness")
    parser.add_argument("root", type=Path, help="already materialized source checkout")
    parser.add_argument("--expected-commit", help="required full source commit")
    parser.add_argument("--receipt", type=Path, help="compare with a previously reviewed JSON receipt")
    parser.add_argument("--home", type=Path, help="check local installed link targets")
    args = parser.parse_args()
    try:
        receipt = source_receipt(args.root, expected_commit=args.expected_commit)
        result = {"source": receipt}
        if args.receipt:
            result["comparison"] = compare_receipt(args.root, json.loads(args.receipt.read_text()))
        if args.home:
            result["installation"] = installed_links(args.root, args.home)
        print(json.dumps(result, indent=2))
        if args.receipt and not result["comparison"]["ready"]:
            raise SystemExit(1)
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        print(json.dumps({"source": "unavailable", "reason": str(exc)}))
        raise SystemExit(1)


if __name__ == "__main__":
    main()
