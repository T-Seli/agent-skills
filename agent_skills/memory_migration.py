"""Memory migration dry run: inventory memory files and render a reviewable plan.

`python3 -m agent_skills.memory_migration plan` reads the memory directories named in
workers.json `memory_dirs` and writes a plan and a unified diff under workers.json
`memory_migration_drafts`. Memory files are opened read-only; nothing is applied.

The script inventories, counts and renders. Each file's destination is a judgment
recorded in `classification.json` inside the drafts directory:
  {"<memory file path>": {"destination": "skill|knowledge|memory", "reason": "<one line>",
                          "target": "<skill or contract file>",            # skill
                          "kind": "decision|lesson|answered", "scope": "global|tenant:<id>|repo:<name>"}}  # knowledge
"""
import argparse
import difflib
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

CONFIG_KEYS = ('memory_dirs', 'memory_migration_drafts')
DESTINATIONS = ('skill', 'knowledge', 'memory')
KINDS = ('decision', 'lesson', 'answered')  # conveyor.json knowledge.functions.record
SCOPE = re.compile(r'global|tenant:[\w.-]+|repo:[\w.-]+')
CLASSIFICATION = 'classification.json'
PLAN = 'plan.json'
DIFF = 'plan.diff'
REPO = Path(__file__).resolve().parents[1]


def load_config():
    path = Path(os.environ.get('AGENT_SKILLS_CONFIG', '~/.config/agent-skills/workers.json')).expanduser()
    if not path.is_file():
        raise SystemExit(f'memory_migration: config {path} not found; it needs {" and ".join(CONFIG_KEYS)}')
    cfg = json.loads(path.read_text())
    if any(k not in cfg for k in CONFIG_KEYS):
        raise SystemExit(f'memory_migration: {path} lacks `memory_dirs` (list of memory directories) '
                         f'and/or `memory_migration_drafts` (directory outside the repo and memory); '
                         f'missing: {", ".join(k for k in CONFIG_KEYS if k not in cfg)}')
    dirs = cfg['memory_dirs']
    if not isinstance(dirs, list) or not dirs or not all(isinstance(d, str) for d in dirs):
        raise SystemExit('memory_migration: `memory_dirs` must be a non-empty list of paths')
    mem = [Path(d).expanduser().resolve() for d in dirs]
    for d in mem:
        if not d.is_dir():
            raise SystemExit(f'memory_migration: memory directory {d} does not exist')
    drafts = Path(cfg['memory_migration_drafts']).expanduser().resolve()
    for other in [REPO, *mem]:
        if drafts == other or other in drafts.parents or drafts in other.parents:
            raise SystemExit(f'memory_migration: drafts directory {drafts} must be outside {other}')
    return mem, drafts


def frontmatter(text):
    """Return ({key: value}, body). Top-level keys only, plus metadata.type as `type`."""
    lines = text.split('\n')
    if not lines or lines[0].strip() != '---' or '---' not in [l.strip() for l in lines[1:]]:
        return None, text
    end = [l.strip() for l in lines[1:]].index('---') + 1
    meta, in_metadata = {}, False
    for line in lines[1:end]:
        m = re.match(r'(\s*)([\w-]+):\s*(.*)$', line)
        if not m:
            continue
        indent, key, value = m.groups()
        if indent and in_metadata:
            meta[f'metadata.{key}'] = value.strip()
        elif not indent:
            in_metadata = key == 'metadata'
            meta[key] = value.strip()
    return meta, '\n'.join(lines[end + 1:]).lstrip('\n')


def inventory(mem_dirs):
    files = []
    for d in mem_dirs:
        for p in sorted(d.glob('*.md')):
            if p.name == 'MEMORY.md':
                continue
            text = p.read_text()
            meta, body = frontmatter(text)
            files.append({'path': str(p), 'dir': str(d), 'name': p.name,
                          'frontmatter': meta is not None,
                          'type': (meta or {}).get('metadata.type') or (meta or {}).get('type'),
                          'title': (meta or {}).get('name'),
                          'date': datetime.fromtimestamp(p.stat().st_mtime, timezone.utc).date().isoformat(),
                          'body': body.strip()})
    return files


def classify(files, drafts):
    path = drafts / CLASSIFICATION
    table = json.loads(path.read_text()) if path.is_file() else {}
    unknown = sorted(set(table) - {f['path'] for f in files})
    if unknown:
        raise SystemExit(f'memory_migration: {path} names files not in the inventory: {", ".join(unknown)}')
    for f in files:
        c = table.get(f['path'])
        if c is None:
            f.update(destination='unclassified')
            continue
        dest = c.get('destination')
        reason = c.get('reason', '')
        problems = []
        if dest not in DESTINATIONS:
            problems.append(f'destination must be one of {DESTINATIONS}')
        if not reason or '\n' in reason:
            problems.append('reason must be one non-empty line')
        if dest == 'skill' and not c.get('target'):
            problems.append('skill destination needs `target`')
        if dest == 'knowledge' and (c.get('kind') not in KINDS or not SCOPE.fullmatch(c.get('scope', ''))):
            problems.append(f'knowledge destination needs kind in {KINDS} and scope global|tenant:<id>|repo:<name>')
        if problems:
            raise SystemExit(f'memory_migration: {f["path"]}: {"; ".join(problems)}')
        f.update({k: c[k] for k in ('destination', 'reason', 'target', 'kind', 'scope') if k in c})
    return files


def slug(name):
    return re.sub(r'[^a-z0-9]+', '-', Path(name).stem.lower()).strip('-')


def proposed_text(files):
    """{label: text} of the new text each destination would receive."""
    out = {}
    for f in files:
        if f['destination'] == 'skill':
            label = f'skill/{f["target"]}'
            head = f'# Proposed additions to {f["target"]} (handed to T4)\n'
            block = f'\n## from {f["name"]} ({f["type"]})\nReason: {f["reason"]}\n\n{f["body"]}\n'
        elif f['destination'] == 'knowledge':
            label = f'knowledge/{f["scope"]}'
            head = f'# Proposed knowledge records, scope {f["scope"]} (handed to the knowledge session)\n'
            block = (f'\n## record(kind={f["kind"]}, id={slug(f["name"])}, date={f["date"]}, '
                     f'source=memory:{f["name"]}, scope={f["scope"]})\nReason: {f["reason"]}\n\n{f["body"]}\n')
        else:
            continue
        out[label] = out.get(label, head) + block
    return out


def index_diffs(files, mem_dirs):
    """Unified diffs of each MEMORY.md with the moved files' lines removed."""
    moved = {f['name'] for f in files if f['destination'] in ('skill', 'knowledge')}
    chunks = []
    for d in mem_dirs:
        index = d / 'MEMORY.md'
        if not index.is_file():
            continue
        before = index.read_text().splitlines(keepends=True)
        gone = {f['name'] for f in files if f['dir'] == str(d)} & moved
        after = [l for l in before if not any(f'({n})' in l for n in gone)]
        chunks += difflib.unified_diff(before, after, f'a{index}', f'b{index}')
    return ''.join(chunks)


def render(files, mem_dirs):
    diff = index_diffs(files, mem_dirs)
    for label, text in sorted(proposed_text(files).items()):
        diff += ''.join(difflib.unified_diff([], text.splitlines(keepends=True), '/dev/null', f'b/{label}'))
    return diff


def write_drafts(drafts, mem_dirs, plan, diff):
    drafts.mkdir(parents=True, exist_ok=True)
    for name, content in ((PLAN, json.dumps(plan, indent=2) + '\n'), (DIFF, diff)):
        target = (drafts / name).resolve()
        if drafts not in target.parents or any(m in target.parents for m in mem_dirs):
            raise SystemExit(f'memory_migration: refusing to write {target}')
        target.write_text(content)


def plan():
    mem_dirs, drafts = load_config()
    files = classify(inventory(mem_dirs), drafts)
    counts = {d: 0 for d in (*DESTINATIONS, 'unclassified')}
    for f in files:
        counts[f['destination']] += 1
    summary = [{k: v for k, v in f.items() if k not in ('body', 'dir')} for f in files]
    write_drafts(drafts, mem_dirs, {'counts': counts, 'files': summary}, render(files, mem_dirs))
    print(json.dumps({'counts': counts, 'files': len(files), 'plan': str(drafts / PLAN), 'diff': str(drafts / DIFF)}))
    if counts['unclassified']:
        print(f'memory_migration: {counts["unclassified"]} files unclassified; add them to '
              f'{drafts / CLASSIFICATION}', file=sys.stderr)
        return 1
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(prog='memory_migration', description=__doc__.split('\n')[0])
    ap.add_argument('command', choices=['plan'])
    ap.parse_args(argv)
    return plan()


if __name__ == '__main__':
    sys.exit(main())
