"""Byte budgets, long-line caps, single-home and duplicate-text checks for guidance files.

Config: skills/budgets.json and skills/homes.json. A cap may only fall: a file over its cap
fails, and so does a cap more than 5% above the file's size (run `--ratchet` after a shrink).
"""
import json
import math
import re
import sys
from pathlib import Path

LONG = 600
SHINGLE = 12
HEADROOM = 1.05


def scope(tracked):
    return sorted(p for p in tracked if p.endswith(".md") and (
        p.startswith("skills/") or p in ("ENGINEERING-COORDINATOR.md", "CLAUDE.md", "global/CLAUDE.md")
        or p.startswith(("output-styles/", "agents/"))))


def read(root, p):
    return (Path(root) / p).read_text(encoding="utf-8")


def measure(root, files):
    out = {}
    for p in files:
        t = read(root, p)
        out[p] = {"bytes": len(t.encode()), "long": sum(1 for l in t.split("\n") if len(l) > LONG)}
    return out


def shingles(t):
    w = re.findall(r"[a-z0-9`_.<>/-]+", t.lower())
    return {" ".join(w[i:i + SHINGLE]) for i in range(len(w) - SHINGLE + 1)}


def dup_count(root, files):
    seen, dup = {}, set()
    for p in files:
        for s in shingles(read(root, p)):
            if s in seen and seen[s] != p:
                dup.add(s)
            seen.setdefault(s, p)
    return len(dup)


def lint(root, tracked):
    root = Path(root)
    fails = []
    files = scope(tracked)
    try:
        cfg = json.loads((root / "skills/budgets.json").read_text())
        homes = json.loads((root / "skills/homes.json").read_text())
    except FileNotFoundError as e:
        return [f"FAIL budget: missing {e.filename}"]
    caps = cfg["files"]
    m = measure(root, files)
    for p in files:
        if p not in caps:
            fails.append(f"FAIL budget: {p} has no entry in skills/budgets.json")
            continue
        cap, size = caps[p], m[p]
        if size["bytes"] > cap["bytes"]:
            fails.append(f"FAIL budget: {p} is {size['bytes']} bytes > cap {cap['bytes']}; shrink it or move text to its single home")
        elif cap["bytes"] > math.ceil(size["bytes"] * HEADROOM):
            fails.append(f"FAIL budget: {p} cap {cap['bytes']} is above size {size['bytes']}; run python3 tests/budget_lint.py --ratchet")
        if size["long"] > cap["long"]:
            fails.append(f"FAIL budget: {p} has {size['long']} lines over {LONG} chars (cap {cap['long']}); break them up")
        elif cap["long"] > size["long"]:
            fails.append(f"FAIL budget: {p} long-line cap {cap['long']} is above {size['long']}; run python3 tests/budget_lint.py --ratchet")
    for p in caps:
        if p not in m:
            fails.append(f"FAIL budget: skills/budgets.json lists {p}, which is not a tracked guidance file")
    n = dup_count(root, files)
    if n > cfg["duplicate_runs"]:
        fails.append(f"FAIL duplicate: {n} {SHINGLE}-word runs appear in two files (cap {cfg['duplicate_runs']}); state each rule once")
    elif cfg["duplicate_runs"] > math.ceil(n * HEADROOM) + 2:
        fails.append(f"FAIL duplicate: cap {cfg['duplicate_runs']} is above {n}; run python3 tests/budget_lint.py --ratchet")
    texts = {p: read(root, p) for p in files}
    for h in homes["homes"]:
        rx, home, allow = re.compile(h["pattern"]), h["home"], set(h.get("also", []))
        have = {p for p, t in texts.items() if rx.search(t)}
        if home not in have:
            fails.append(f"FAIL home: `{h['id']}` is not in its home {home}")
        for p in sorted(have - {home} - allow):
            fails.append(f"FAIL home: `{h['id']}` belongs only in {home}, found in {p}; reference it instead")
        for p in sorted(allow - have):
            fails.append(f"FAIL home: `{h['id']}` no longer appears in {p}; drop it from `also` in skills/homes.json")
    return fails


def ratchet(root, tracked):
    root = Path(root)
    files = scope(tracked)
    path = root / "skills/budgets.json"
    old = json.loads(path.read_text()) if path.exists() else {"files": {}}
    m = measure(root, files)
    new = {p: {"bytes": min(old["files"].get(p, m[p])["bytes"], m[p]["bytes"]),
               "long": min(old["files"].get(p, m[p])["long"], m[p]["long"])} for p in files}
    n = dup_count(root, files)
    cfg = {"unit": "bytes; tokens ~ bytes/3.9", "long_line_chars": LONG,
           "duplicate_runs": min(old.get("duplicate_runs", n), n), "files": new}
    path.write_text(json.dumps(cfg, indent=1, sort_keys=False) + "\n")
    return cfg


if __name__ == "__main__":
    import subprocess
    tracked = subprocess.run(["git", "ls-files"], capture_output=True, text=True, check=True).stdout.split()
    if "--ratchet" in sys.argv:
        c = ratchet(".", tracked)
        print(f"ratcheted {len(c['files'])} files; duplicate runs {c['duplicate_runs']}")
    else:
        f = lint(".", tracked)
        print("\n".join(f) or "ok")
        sys.exit(1 if f else 0)
