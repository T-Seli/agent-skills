#!/bin/sh
# Framework checks: README budgets, banned names, invocation, contracts path, template fields.
# Prints one "FAIL <id>: <detail>" line per problem; exits 1 if any.
# An optional private banned-name list can add local checks without entering the repo.
set -eu
cd "$(dirname "$0")/.."
export BANNED="${FRAMEWORK_BANNED_NAMES:-$HOME/.config/claude-skills/banned-names.txt}"
exec python3 - <<'EOF'
import os, re, subprocess, sys

fails = []
def fail(check, detail): fails.append(f"FAIL {check}: {detail}")

listed = subprocess.run(["git", "ls-files"], capture_output=True, text=True)
if listed.returncode == 0 and listed.stdout.strip():
    tracked = listed.stdout.splitlines()
else:  # clean source snapshot without Git history
    from pathlib import Path
    tracked = [str(p) for p in Path('.').rglob('*') if p.is_file() and not any(
        x in {'.git', '__pycache__', '.pytest_cache'} for x in p.parts)]
def text(p): return open(p, encoding="utf-8").read()
def words(p): return len(text(p).split())
def lines(p): return text(p).count("\n")

CONTRACTS = "skills/workflow-contracts/contracts.md"
TEMPLATE = "skills/workflow-contracts/project-CLAUDE-template.md"

# Budgets (README § Change the framework).
budgets = [("global/CLAUDE.md", words, 600), (CONTRACTS, lines, 90), (TEMPLATE, words, 1000),
           ("CLAUDE.md", words, 1000), ("output-styles/orchestrator.md", lines, 25), ("agents/scout.md", lines, 25)]
budgets += [(p, lines, 100) for p in tracked if re.fullmatch(r"skills/[^/]+/SKILL\.md", p)]
budgets += [(p, lines, 80) for p in tracked if re.fullmatch(r"skills/[^/]+/references/[^/]+\.md", p)]
for path, measure, cap in budgets:
    if not os.path.exists(path): fail("missing", path); continue
    n = measure(path)
    if n > cap: fail("budget", f"{path} is {n} > {cap} {'words' if measure is words else 'lines'}")

# Skill frontmatter: name matches folder, description ≤300 chars, model-invocable.
for p in tracked:
    m = re.fullmatch(r"skills/([^/]+)/SKILL\.md", p)
    if not m: continue
    fm = re.match(r"---\n(.*?)\n---\n", text(p), re.S)
    if not fm: fail("frontmatter", p); continue
    fields = dict(l.split(":", 1) for l in fm.group(1).splitlines() if ":" in l and not l.startswith(" "))
    if fields.get("name", "").strip() != m.group(1): fail("name", p)
    desc = fields.get("description", "").strip().strip("'\"").replace("''", "'")
    if not desc or len(desc) > 300: fail("description", f"{p} is {len(desc)} chars")
    if fields.get("disable-model-invocation", "").strip() == "true": fail("invocation", f"{p} cannot start on its own")

# Old contracts path.
for p in tracked:
    if not p.startswith("tests/") and p.endswith((".md", ".sh", ".py", ".toml", ".json")) and "~/.claude/workflow" in text(p):
        fail("contracts-path", f"{p} still reads ~/.claude/workflow")

# Banned names (private list).
banned = os.environ["BANNED"]
if not os.path.exists(banned) and os.environ.get('FRAMEWORK_BANNED_NAMES'):
    fail("banned-list", "explicit private banned-name list not found")
elif os.path.exists(banned):
    names = [l.strip().lower() for l in text(banned).splitlines() if l.strip() and not l.startswith("#")]
    for p in tracked:
        body = text(p).lower()
        for n in names:
            if n in body: fail("name", f"{p} contains a banned name")

# Every project field a skill reads (§ Section `Field`) exists in the template.
if os.path.exists(TEMPLATE):
    template = text(TEMPLATE)
    refs = set()
    for p in tracked:
        if p.startswith("skills/") and p.endswith(".md"):
            refs |= set(re.findall(r"§ (?:Map|Run & test|Deploy|Observe|Tenancy) `([^`<]+)`", text(p)))
    for f in sorted(refs - {"none"}):
        if ":" in f: continue  # a value such as `Release: batched`, not a field name
        if not re.search(rf"(^- | · ){re.escape(f)}:", template, re.M): fail("field", f"template lacks `{f}`")

# Production reads go through the shared data-access rules.
if not os.path.exists("skills/workflow-contracts/data-access.md"):
    fail("missing", "skills/workflow-contracts/data-access.md")
for p in ("skills/blueprint/SKILL.md", "skills/blueprint/references/bug-mode.md", "skills/monitor/SKILL.md"):
    if os.path.exists(p) and "data-access.md" not in text(p):
        fail("data-access", f"{p} does not cite data-access.md")

print("\n".join(fails) if fails else "ok")
sys.exit(1 if fails else 0)
EOF
