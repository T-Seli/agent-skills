"""Knowledge stores: a brain (decisions, lessons, answers, inbox, log) and a repo wiki, both plain markdown."""
import datetime
import json
import math
import os
import posixpath
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

NOT_CONFIGURED = 'brain: not configured on this machine'
TABLES = {'decision': 'decisions.md', 'lesson': 'lessons.md', 'answered': 'answered.md'}
KEYS = ('kind', 'id', 'date', 'source', 'scope', 'text')
STOP = {'the', 'and', 'for', 'are', 'was', 'does', 'did', 'has', 'have', 'how', 'what', 'who', 'why', 'can', 'may'}
STATUSES = ('decided', 'shadow', 'enforced', 'superseded')
KEBAB = re.compile(r'[a-z0-9]+(-[a-z0-9]+)*')
SCOPE = re.compile(r'global|tenant:[^\s|]+|repo:[^\s|]+')
VERIFIED = re.compile(r'^verified: (\d{4}-\d{2}-\d{2}) @ ([0-9a-f]{7,40})$', re.M)
CODE = re.compile(r'^code:\s*(.+)$', re.M)
LINK = re.compile(r'\[[^\]]*\]\(([^)\s]+)\)')
INBOX_NAME = re.compile(r'^\d{8}T\d{6}Z-(decision|lesson|answered)-(.+)\.md$')
SECRETS = [
    (re.compile(r'AKIA[0-9A-Z]{16}'), 'AWS access key'),
    (re.compile(r'-----BEGIN [A-Z ]*PRIVATE KEY-----'), 'private key'),
    (re.compile(r'\bsk-[A-Za-z0-9_-]{20,}'), 'API key'),
    (re.compile(r'\bxox[abprs]-[A-Za-z0-9-]{10,}'), 'Slack token'),
    (re.compile(r'\bBearer\s+[A-Za-z0-9._~+/-]{20,}'), 'bearer token'),
    (re.compile(r'\b(?:password|passwd|secret|api[_-]?key|token)\s*[:=]\s*\S{4,}', re.I), 'credential assignment'),
    (re.compile(r'[\w.+-]+@[\w-]+\.[\w.-]+'), 'email address'),
    (re.compile(r'(?:\+1[ .-]?)?\(?\b\d{3}\)?[ .-]\d{3}[ .-]\d{4}\b'), 'phone number'),
]


class KnowledgeError(ValueError):
    pass


def _git(cwd, *args, check=True):
    done = subprocess.run(['git', '-C', str(cwd), *args], capture_output=True, text=True)
    if check and done.returncode:
        raise KnowledgeError(f'git {" ".join(args)} failed in {cwd}: {done.stderr.strip()}')
    return done.stdout.strip()


def _md_files(directory):
    return sorted(p for p in Path(directory).glob('*.md') if not p.name.startswith('.')) if Path(directory).is_dir() else []


def _cells(line):
    line = line.strip()
    line = line[1:] if line.startswith('|') else line
    line = line[:-1] if line.endswith('|') else line
    return [c.strip() for c in line.split('|')]


def _tables(text):
    """Markdown tables as (start, end, header, rows): line span, lowercased header cells, data rows."""
    lines, out, i = text.split('\n'), [], 0
    while i < len(lines):
        if not lines[i].lstrip().startswith('|'):
            i += 1
            continue
        start = i
        while i < len(lines) and lines[i].lstrip().startswith('|'):
            i += 1
        cells = [_cells(l) for l in lines[start:i]]
        rows = [c for c in cells[1:] if not all(re.fullmatch(r':?-{3,}:?', x) for x in c)]
        out.append((start, i, [h.lower() for h in cells[0]], rows))
    return out


def _first_table(path):
    tables = _tables(path.read_text(encoding='utf-8')) if path.exists() else []
    return tables[0] if tables else None


def _norm(href):
    href = href.split('#')[0]
    return None if '://' in href else posixpath.normpath(href)


def _routing(store):
    """Rows of the routing table (the one with a Domain column) in index.md: (domain, linked page, row)."""
    index = store / 'index.md'
    out = []
    for _, _, header, rows in _tables(index.read_text(encoding='utf-8')) if index.exists() else []:
        if 'domain' not in header:
            continue
        col = header.index('domain')
        for row in rows:
            link = LINK.search(' '.join(row))
            out.append((row[col] if col < len(row) else '', _norm(link.group(1)) if link else None, row))
    return out


def _tokens(text):
    return set(re.findall(r'[a-z0-9_-]{3,}', text.lower()))


def _entry(path):
    data = {}
    for line in path.read_text(encoding='utf-8').splitlines():
        key, sep, value = line.partition(': ')
        if sep and key in KEYS:
            data[key] = value.strip()
    return data


def _date_ok(value, month=False):
    try:
        datetime.datetime.strptime(value, '%Y-%m' if month else '%Y-%m-%d')
    except ValueError:
        return False
    return bool(re.fullmatch(r'\d{4}-\d{2}' if month else r'\d{4}-\d{2}-\d{2}', value))


def _timeline_patterns():
    path = Path(__file__).resolve().parent.parent / 'skills' / 'workflow-contracts' / 'conveyor.json'
    data = json.loads(path.read_text(encoding='utf-8'))['timeline']
    return re.compile(data['pattern']), re.compile(data['correction'])


def _stamp():
    return datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')


def _remove_worktree(brain, worktree):
    _git(brain, 'worktree', 'remove', '--force', str(worktree), check=False)
    shutil.rmtree(worktree.parent, ignore_errors=True)


def _fold_text(text, entries, name):
    """Text with one row per inbox entry added after the first table's last row, mapped by header names."""
    table = next(iter(_tables(text)), None)
    if not table:
        raise KnowledgeError(f'{name} has no table to fold into')
    _, end, header, _ = table
    rows = []
    for e in entries:
        values = {'id': e['id'], 'date': e['date'], 'source': e['source'], 'scope': e['scope']}
        if e['kind'] == 'decision':
            values.update(status='decided', switch='-', rule=e['text'])
        else:
            first, _, second = e['text'].partition(' => ')
            names = ('what happened', 'rule now') if e['kind'] == 'lesson' else ('question', 'answer')
            values.update({names[0]: first, names[1]: second})
        unknown = [h for h in header if h not in values]
        if unknown:
            raise KnowledgeError(f'{name} has columns collect cannot fill: {", ".join(unknown)}')
        rows.append('| ' + ' | '.join(values[h] for h in header) + ' |')
    lines = text.split('\n')
    lines[end:end] = rows
    return '\n'.join(lines)


def _move_folded(root, entries):
    """Move inbox files into inbox/folded/; returns (from, to) pairs for undo."""
    (root / 'inbox' / 'folded').mkdir(parents=True, exist_ok=True)
    pairs = [(root / 'inbox' / n, root / 'inbox' / 'folded' / n) for n in entries]
    for src, dst in pairs:
        os.replace(src, dst)
    return pairs


class Knowledge:
    def __init__(self, brain, wiki, notice):
        self.brain, self.wiki, self.notice = brain, wiki, notice

    @classmethod
    def open(cls, brain=None, wiki=None, config_path=None):
        path = Path(config_path or os.environ.get('AGENT_SKILLS_CONFIG', '~/.config/agent-skills/workers.json')).expanduser()
        stores = {}
        if path.exists():
            try:
                stores = json.loads(path.read_text(encoding='utf-8')).get('knowledge_stores', {})
            except ValueError as error:
                raise KnowledgeError(f'{path} is not valid JSON: {error}')
            if not isinstance(stores, dict):
                raise KnowledgeError(f'{path}: knowledge_stores must be an object')
        mapped = Path(stores[brain]).expanduser() if brain and brain in stores else None
        brain_path = mapped if mapped and mapped.is_dir() else None
        wiki_path = Path(wiki).expanduser() if wiki else None
        if wiki_path and not wiki_path.is_dir():
            raise KnowledgeError(f'wiki directory not found: {wiki_path}')
        return cls(brain_path, wiki_path, None if brain_path else NOT_CONFIGURED)

    def _stores(self):
        return [(n, p) for n, p in (('brain', self.brain), ('wiki', self.wiki)) if p]

    def _need_brain(self):
        if not self.brain:
            raise KnowledgeError(NOT_CONFIGURED)
        return self.brain

    # reads

    @staticmethod
    def _unfolded(store, strict=False):
        """[(path, entry)] for inbox/*.md; a file missing keys is skipped on reads and refused when strict."""
        out = []
        for path in _md_files(store / 'inbox'):
            entry = _entry(path)
            if all(entry.get(k) for k in KEYS):
                out.append((path, entry))
            elif strict:
                raise KnowledgeError(f'inbox file is missing keys: {path.name}')
        return out

    def domains(self):
        return sorted({d for _, s in self._stores() for d, _, _ in _routing(s) if re.fullmatch(r'[a-z-]+', d)})

    def pages(self, domain):
        out, seen = [], set()
        for name, store in self._stores():
            pending = {e['kind'] for _, e in self._unfolded(store)}
            for dom, link, _ in _routing(store):
                if dom != domain or not link or (name, link) in seen:
                    continue
                seen.add((name, link))
                page = store / link
                found = VERIFIED.search(page.read_text(encoding='utf-8')) if page.is_file() else None
                kind = next((k for k, f in TABLES.items() if f == link), None)
                out.append({'store': name, 'path': link, 'verified': found and found.group(1),
                            'sha': found and found.group(2), 'pending': kind in pending})
        return out

    def find(self, words):
        wanted = _tokens(' '.join(words)) - STOP
        if not wanted:
            raise KnowledgeError('find needs at least one word of 3+ characters that is not a stop word')
        need, hits = math.ceil(len(wanted) / 2), []
        for name, store in self._stores():
            for rel, kind in (('decisions.md', 'decision'), ('answered.md', 'answered')):
                table = _first_table(store / rel)
                for row in table[3] if table else []:
                    cell = dict(zip(table[2], row))
                    if kind == 'decision':
                        ident, text = row[0], cell.get('rule', '')
                    else:
                        ident, text = cell.get('id'), f"{cell.get('question', '')} => {cell.get('answer', '')}"
                    hits.append((rel, ident, text, name, False, ' '.join(row)))
            for path, entry in self._unfolded(store):
                hits.append((f'inbox/{path.name}', entry['id'], entry['text'], name, True, f"{entry['id']} {entry['text']}"))
        found = []
        for file, ident, text, name, pending, haystack in hits:
            score = len(wanted & _tokens(haystack))
            if score >= need:
                found.append({'file': file, 'id': ident, 'text': text, 'source': name, 'score': score, 'pending': pending})
        return sorted(found, key=lambda h: -h['score'])[:5]

    # writes

    def record(self, kind, id, date, source, text, scope='global'):
        brain = self._need_brain()
        if kind not in TABLES:
            raise KnowledgeError(f'kind must be one of {", ".join(TABLES)}')
        if not KEBAB.fullmatch(id):
            raise KnowledgeError(f'id must be kebab-case: {id!r}')
        if not _date_ok(date) and not (kind == 'lesson' and _date_ok(date, month=True)):
            raise KnowledgeError(f'date must be YYYY-MM-DD{" or YYYY-MM" if kind == "lesson" else ""}: {date!r}')
        if not SCOPE.fullmatch(scope):
            raise KnowledgeError(f'scope must be global, tenant:<id> or repo:<name>: {scope!r}')
        for label, value in (('source', source), ('text', text)):
            if not value or value != value.strip() or '\n' in value or '|' in value:
                raise KnowledgeError(f'{label} must be one trimmed non-empty line without "|"')
        if kind != 'decision' and ' => ' not in text:
            shape = '<what happened> => <rule now>' if kind == 'lesson' else '<question> => <answer>'
            raise KnowledgeError(f'{kind} text must be "{shape}"')
        if id in self._known_ids(brain, kind):
            raise KnowledgeError(f'{kind} id already exists: {id}')
        path = brain / 'inbox' / f'{_stamp()}-{kind}-{id}.md'
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, 'x', encoding='utf-8') as handle:
            handle.write(''.join(f'{k}: {v}\n' for k, v in zip(KEYS, (kind, id, date, source, scope, text))))
        return {'path': path.relative_to(brain).as_posix()}

    @staticmethod
    def _known_ids(brain, kind):
        ids = set()
        table = _first_table(brain / TABLES[kind])
        if table and 'id' in table[2]:
            ids |= {row[table[2].index('id')] for row in table[3] if len(row) == len(table[2])}
        for folder in (brain / 'inbox', brain / 'inbox' / 'folded'):
            for path in _md_files(folder):
                m = INBOX_NAME.match(path.name)
                if m and m.group(1) == kind:
                    ids.add(m.group(2))
        return ids

    def collect(self):
        brain = self._need_brain()
        entries = self._unfolded(brain, strict=True)
        if not entries:
            return {'folded': [], 'pr': None}
        if _git(brain, 'status', '--porcelain', '--', 'decisions.md', 'inbox'):
            raise KnowledgeError('decisions.md or inbox/ has uncommitted changes; commit or discard them first')
        decisions = [(p, e) for p, e in entries if e['kind'] == 'decision']
        others = [(p, e) for p, e in entries if e['kind'] != 'decision']
        branch = worktree = original = None
        moved = []
        try:
            if others:
                branch = f'collect/{_stamp()}'
                worktree = self._fold_branch(brain, branch, others)
            if decisions:
                table = brain / 'decisions.md'
                original = table.read_text(encoding='utf-8')
                table.write_text(_fold_text(original, [e for _, e in decisions], table.name), encoding='utf-8')
                moved = _move_folded(brain, [p.name for p, _ in decisions])
                self._abort_on_lint(brain)
            if worktree:
                _git(worktree, 'add', '-A')
                _git(worktree, 'commit', '-q', '-m', f'knowledge: fold {len(others)} inbox entries')
            if decisions:
                _git(brain, 'add', '-A', '--', 'decisions.md', 'inbox')
                _git(brain, 'commit', '-q', '-m', f'knowledge: fold {len(decisions)} decisions', '--', 'decisions.md', 'inbox')
        except BaseException:
            if original is not None:
                (brain / 'decisions.md').write_text(original, encoding='utf-8')
                for src, dst in moved:
                    os.replace(dst, src)
            if worktree:
                _remove_worktree(brain, worktree)
                _git(brain, 'branch', '-D', branch, check=False)
            raise
        if worktree:
            _remove_worktree(brain, worktree)
        return {'folded': [e['id'] for _, e in entries], 'pr': branch}

    def _fold_branch(self, brain, branch, others):
        """Fold lessons and answers into their tables in a new temporary worktree on `branch`; returns its path."""
        worktree = Path(tempfile.mkdtemp(prefix='knowledge-')) / 'wt'
        try:
            _git(brain, 'worktree', 'add', '-q', '-b', branch, str(worktree), 'HEAD')
            for kind in ('lesson', 'answered'):
                mine = [e for _, e in others if e['kind'] == kind]
                if mine:
                    table = worktree / TABLES[kind]
                    table.write_text(_fold_text(table.read_text(encoding='utf-8'), mine, table.name), encoding='utf-8')
            _move_folded(worktree, [p.name for p, _ in others])
            self._abort_on_lint(worktree)
        except BaseException:
            _remove_worktree(brain, worktree)
            _git(brain, 'branch', '-D', branch, check=False)
            raise
        return worktree

    def _abort_on_lint(self, root):
        failures = self._lint_store('brain', root)
        if failures:
            raise KnowledgeError('lint failed after folding; nothing was kept:\n' + '\n'.join(failures))

    # log

    def log(self, issue, lines):
        brain = self._need_brain()
        if not re.fullmatch(r'\d+', str(issue)):
            raise KnowledgeError(f'issue must be a number: {issue!r}')
        if not lines:
            raise KnowledgeError('log needs at least one timeline line')
        pattern, correction = _timeline_patterns()
        month = None
        for line in lines:
            if '\n' in line or not (pattern.match(line) or correction.match(line)):
                raise KnowledgeError(f'not a timeline line: {line!r}')
            if month is None and pattern.match(line):
                month = pattern.match(line).group('time')[:7]
        heading = f'## #{issue}'
        target = next((p for p in _md_files(brain / 'log') if re.search(rf'(?m)^{heading}$', p.read_text(encoding='utf-8'))), None)
        if target is None:
            if month is None:
                raise KnowledgeError('log needs a timeline line to choose the month')
            target = brain / 'log' / f'{month}.md'
        text = target.read_text(encoding='utf-8') if target.exists() else f'# Log {target.stem}\n'
        head, *sections = re.split(r'(?m)^(?=## #)', text)
        new = f'{heading}\n' + '\n'.join(lines) + '\n'
        for i, section in enumerate(sections):
            if section.split('\n', 1)[0] == heading:
                sections[i] = new
                break
        else:
            sections.append(new)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(head.rstrip('\n') + '\n' + ''.join('\n' + s.rstrip('\n') + '\n' for s in sections), encoding='utf-8')
        return {'path': target.relative_to(brain).as_posix()}

    # stale

    def stale(self):
        out = []
        for name, store in self._stores():
            root = None
            for path in sorted(store.rglob('*.md')):
                rel = path.relative_to(store).as_posix()
                if rel.split('/')[0] in ('inbox', 'log', '.git') or path.name.startswith('.'):
                    continue
                text = path.read_text(encoding='utf-8')
                verified, code = VERIFIED.search(text), CODE.search(text)
                if not (verified and code):
                    continue
                root = root or _git(store, 'rev-parse', '--show-toplevel')
                paths = [p.split('#')[0].strip() for p in code.group(1).split(',') if p.strip()]
                try:
                    changed = _git(root, 'diff', '--name-only', f'{verified.group(2)}..HEAD', '--', *paths).split()
                except KnowledgeError as error:
                    raise KnowledgeError(f'{name}:{rel}: cannot compare from {verified.group(2)}: {error}')
                if changed:
                    out.append({'store': name, 'path': rel, 'verified': verified.group(1), 'changed': changed})
        return out

    # lint

    def lint(self):
        return [f for name, store in self._stores() for f in self._lint_store(name, store)]

    def _lint_store(self, name, store):
        out = []
        for path in sorted(store.rglob('*.md')):
            rel = path.relative_to(store).as_posix()
            if '.git' in path.relative_to(store).parts or path.name.startswith('.'):
                continue
            text = path.read_text(encoding='utf-8')
            for number, line in enumerate(text.split('\n'), 1):
                out += [f'{name}:{rel}: line {number}: {label}' for rx, label in SECRETS if rx.search(line)]
            top = rel.split('/')[0]
            if top == 'inbox':
                missing = [k for k in KEYS if not _entry(path).get(k)]
                if missing:
                    out.append(f'{name}:{rel}: inbox entry needs keys: {", ".join(missing)}')
            elif top != 'log' and rel not in TABLES.values():
                limit, lines = (60 if rel == 'index.md' else 80), text.count('\n')
                if lines > limit:
                    out.append(f'{name}:{rel}: {lines} lines, budget {limit}')
                if not VERIFIED.search(text):
                    out.append(f'{name}:{rel}: header needs "verified: <date> @ <sha>"')
        out += self._lint_routing(name, store)
        for kind, rel in TABLES.items():
            out += self._lint_table(name, store, kind, rel)
        return out

    @staticmethod
    def _lint_routing(name, store):
        out, linked = [], set()
        for domain, link, row in _routing(store):
            if not re.fullmatch(r'[a-z-]+', domain):
                out.append(f'{name}:index.md: row {row[0]!r} needs a [a-z-]+ domain cell, got {domain!r}')
            if not link:
                out.append(f'{name}:index.md: row {row[0]!r} has no page link')
            elif not (store / link).is_file():
                out.append(f'{name}:index.md: row {row[0]!r} links missing page {link}')
            else:
                linked.add(link)
        for path in sorted((store / 'pages').rglob('*.md')):
            rel = path.relative_to(store).as_posix()
            if rel not in linked:
                out.append(f'{name}:{rel}: page is not linked from index.md')
        return out

    @staticmethod
    def _lint_table(name, store, kind, rel):
        table = _first_table(store / rel)
        out = []
        for row in table[3] if table else []:
            header, cell = table[2], dict(zip(table[2], row))
            problems = []
            if len(row) != len(header):
                problems.append(f'has {len(row)} cells, header has {len(header)}')
            else:
                date = cell.get('date', '')
                if kind == 'decision':
                    if cell.get('status') not in STATUSES:
                        problems.append(f'status must be one of {"|".join(STATUSES)}')
                    if not _date_ok(date):
                        problems.append('date must be YYYY-MM-DD')
                elif not (_date_ok(date) or _date_ok(date, month=True)):
                    problems.append('date must be YYYY-MM or YYYY-MM-DD')
                if not cell.get('source', row[-1]):
                    problems.append('source is empty')
            out += [f"{name}:{rel}: row '{row[0]}': {p}" for p in problems]
        return out
