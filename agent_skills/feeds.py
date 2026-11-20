"""`issues-cli feed`: rows piped from a declared feed become inbox issues, deduped by Source-key (conveyor.md § Feeds).

The caller passes the issues_cli module as `cli`, so its Refused is the one main() catches however it was started."""
import hashlib
import json
import re

UPDATED = re.compile(r'^Source updated: \d{4}-\d{2}-\d{2} \d{2}:\d{2}Z · (.+)$')


def entry(cli, name):
    found = next((e for e in cli.belt()['feeds']['entries'] if e['id'] == name), None)
    if found is None:
        raise cli.Refused(f"unknown feed {name}; declared feeds: {', '.join(e['id'] for e in cli.belt()['feeds']['entries'])}")
    if not found['enabled']:
        raise cli.Refused(f'feed {name} is disabled in conveyor.json feeds.entries; nothing was read or written')
    return found


def source_key(feed, row):
    """A hash of the declared stable fields only: never a row number, never the summary."""
    stable = {f: str(row[f]) for f in sorted(feed['key_fields'])}
    return hashlib.sha256(json.dumps([feed['id'], stable], sort_keys=True).encode()).hexdigest()[:16]


def parse_rows(cli, feed, text):
    """Every row checked before any write; a bad row refuses the whole run. Extra fields are dropped."""
    limit, levels = cli.belt()['feeds']['summary_max'], [p[5:] for p in cli.belt()['labels']['priority']]
    rows = []
    for k, raw in enumerate((x for x in text.split('\n') if x.strip()), 1):
        try:
            r = json.loads(raw)
        except ValueError:
            raise cli.Refused(f'row {k} is not JSON')
        missing = [f for f in (*feed['key_fields'], 'summary', 'link') if not str(r.get(f) or '').strip()]
        if missing:
            raise cli.Refused(f"row {k} lacks {', '.join(missing)}")
        summary, link = str(r['summary']).strip(), str(r['link']).strip()
        level = str(r.get('priority') or feed['priority']).removeprefix('prio:')
        if '\n' in summary or len(summary) > limit:
            raise cli.Refused(f'row {k} summary must be one line of at most {limit} characters')
        if re.search(r'\s', link):
            raise cli.Refused(f'row {k} link has whitespace')
        if level not in levels:
            raise cli.Refused(f"row {k} priority {level} is not one of {', '.join(levels)}")
        rows.append({'key': source_key(feed, r), 'summary': summary, 'link': link, 'level': level})
    return rows


def known(cli, gh, repo, key):
    """(issue number, last summary seen) of the open or closed issue carrying `key`, else None."""
    marker = f'Source-key: {key}'
    for i in json.loads(gh(['issue', 'list', '-R', repo, '--state', 'all', '--limit', '5', '--search',
                            f'"{marker}" in:body', '--json', cli.FIELDS])):
        body = i['body'].replace('\r\n', '\n')
        if marker in body.split('\n'):
            updates = [m[1] for line in cli.comment_lines(i) if (m := UPDATED.match(line))]
            return i['number'], updates[-1] if updates else body.split('\n', 1)[0].strip()
    return None


def run(cli, gh, repo, name, text, log=None):
    feed = entry(cli, name)
    rows, seen, new, updated, skipped = parse_rows(cli, feed, text), set(), 0, 0, 0
    for r in rows:
        if r['key'] in seen:
            skipped += 1
            continue
        seen.add(r['key'])
        found = known(cli, gh, repo, r['key'])
        if found and found[1] == r['summary']:
            skipped += 1
        elif found:
            cli.comment(gh, repo, found[0], [f"Source updated: {cli.stamp(cli.now())} · {r['summary']}"])
            updated += 1
        elif new >= feed['max_new']:
            skipped += 1
        else:
            cli.capture(gh, repo, f"{r['summary']}\n{r['link']}\nSource-key: {r['key']}", r['link'], r['level'], offline_ok=False)
            new += 1
    beat = f'Feed: {cli.stamp(cli.now())} · {name} · new {new} · updated {updated} · skipped {skipped}'
    if not re.fullmatch(cli.belt()['feeds']['heartbeat']['pattern'], beat):
        raise cli.Refused(f'malformed feed heartbeat: {beat}')
    path = cli.task_log(log)[0]
    if path and not isinstance(gh, cli.DryRun):
        with path.open('a') as fh:
            fh.write(beat + '\n')
    return beat
