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


def runtime_capability_receipt(release_root, *, runtime, expected_commit, expected_tree,
                               installed_routes, loaded_bundle, behavior_checks):
    """Bind installed routes, loaded bodies and exercised behavior for one runtime."""
    if runtime not in {"codex", "claude"}:
        raise ValueError("unsupported runtime")
    if (not isinstance(expected_commit, str) or not isinstance(expected_tree, str) or
            len(expected_commit) != 40 or len(expected_tree) != 40 or
            any(char not in "0123456789abcdef" for char in expected_commit + expected_tree)):
        raise ValueError("full expected commit and tree required")
    root = Path(release_root).resolve(strict=True)
    pin_path = root / ".release-pin.json"
    try:
        pin = json.loads(pin_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pin = None
    identity_ready = (isinstance(pin, dict) and pin.get("commit") == expected_commit and
                      pin.get("tree") == expected_tree)
    if not isinstance(installed_routes, dict) or not installed_routes:
        raise ValueError("installed runtime routes required")
    route_checks = {}
    for name, route in installed_routes.items():
        if not isinstance(name, str) or not name or not isinstance(route, (str, Path)):
            raise ValueError("invalid installed runtime route")
        path = Path(route)
        route_checks[name] = path.is_symlink() and path.resolve().is_relative_to(root)
    sources = loaded_bundle.get("sources") if isinstance(loaded_bundle, dict) else None
    load_checks = {}
    if isinstance(sources, list):
        for source in sources:
            if not isinstance(source, dict) or not isinstance(source.get("path"), str) or not isinstance(source.get("sha256"), str):
                load_checks["invalid-source"] = False
                continue
            candidate = root / source["path"]
            safe = (not candidate.is_symlink() and candidate.resolve(strict=False).is_relative_to(root) and
                    candidate.is_file())
            load_checks[source["path"]] = safe and hashlib.sha256(candidate.read_bytes()).hexdigest() == source["sha256"]
    if not isinstance(behavior_checks, list) or not behavior_checks:
        raise ValueError("runtime behavior checks required")
    behavior = []
    for check in behavior_checks:
        if (not isinstance(check, dict) or set(check) != {"id", "outcome", "receipt_ref"} or
                check.get("outcome") not in {"pass", "fail", "blocked"} or
                not all(isinstance(check.get(key), str) and check[key].strip()
                        for key in ("id", "receipt_ref"))):
            raise ValueError("invalid runtime behavior check")
        behavior.append(dict(check))
    routes_ready = all(route_checks.values())
    load_ready = bool(load_checks) and all(load_checks.values())
    behavior_ready = all(check["outcome"] == "pass" for check in behavior)
    return {"runtime": runtime, "commit": expected_commit, "tree": expected_tree,
            "release_root": str(root), "identity_ready": identity_ready,
            "installed_routes": route_checks, "installed_ready": routes_ready,
            "loaded_sources": load_checks, "loaded_ready": load_ready,
            "behavior_checks": behavior, "behavior_ready": behavior_ready,
            "ready": identity_ready and routes_ready and load_ready and behavior_ready}


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
