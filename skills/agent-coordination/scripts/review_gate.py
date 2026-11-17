"""Independent-reviewer gates: sanitized packet, verdict parser, switches, watcher step, value summary.

Pure functions: nothing here sends, reads a channel, merges or approves. A verdict is data; a reviewer NO
against a worker YES always goes to the user.
"""
import hashlib
import re
import statistics

GATES = {
    "g1": "draft PR head before ready",
    "g2": "release candidate",
    "g3": "prompt or skill change against budgets",
    "g4": "deploy record",
    "g5": "monitor verdict",
    "audit": "weekly independent audit",
    "plan": "major plan, spec or decision",
}
DEFAULTS = {"on": True, "deadline_h": 4, "retries": 1}
SHA = re.compile(r"[0-9a-f]{40}")
PRIVATE = re.compile(
    r"gh[pousr]_\w{16,}|github_pat_\w+|xox[a-z]-[\w-]+|sk-\w{16,}|AKIA[0-9A-Z]{16}|-----BEGIN|eyJ[\w-]{5,}\."
    r"|(?i:\b(?:password|passwd|secret|token|api[_-]?key|bearer)\b)|[0-9a-fA-F]{32,}|\b[A-Za-z0-9_+=-]{32,}\b"
    r"|[\w.+-]+@[\w-]+\.\w+|\b[UDCTW][0-9A-Z]{8,}\b|\+?\d[\d\s().-]{8,}\d"
)
FREE = re.compile(r"[A-Za-z0-9 _.,:;()/+=%'#-]{1,200}")  # one line, no control characters, no pipe or at-sign
DIFFSTAT = re.compile(r"\d+ files? changed(, \d+ insertions?\(\+\))?(, \d+ deletions?\(-\))?")
LEDGER_ID = re.compile(r"[A-Z][A-Z0-9-]{0,39}")
VERDICT = re.compile(r"VERDICT (\S+) ([0-9a-f]{40}) ([0-9a-f]{40}) (NO-BLOCKER|BLOCKERS (\d+))")
FINDING = re.compile(r"FINDING (\S+) (P[123]) (\S+) (.+)")


def _clean(label, value, pattern=FREE):
    value = str(value)
    if not pattern.fullmatch(value):
        raise ValueError(f"{label} is empty, multi-line, too long or outside its allowed format")
    if PRIVATE.search(value):
        raise ValueError(f"{label} holds a secret or private id")
    return value


def build_packet(*, gate, head, tree, base, diffstat, tests, done_when, ledger):
    if gate not in GATES:
        raise ValueError(f"unknown gate {gate!r}")
    for label, sha in (("head", head), ("tree", tree), ("base", base)):
        if not SHA.fullmatch(sha or ""):
            raise ValueError(f"{label} must be a full 40-hex sha")
    lines = [f"REVIEW {gate}", f"head {head}", f"tree {tree}", f"base {base}",
             f"diff {_clean('diffstat', diffstat, DIFFSTAT)}", f"tests {_clean('tests', tests)}"]
    lines += [f"done-when {_clean('done_when', d)}" for d in done_when]
    lines += [f"ledger {_clean('ledger id', i, LEDGER_ID)}: {_clean('ledger state', s)}" for i, s in ledger]
    lines.append("reply: VERDICT <gate> <head> <tree> NO-BLOCKER|BLOCKERS <n>, then FINDING <id> <P1|P2|P3> <source> <evidence>; <check>")
    text = "\n".join(lines)
    return {"text": text, "fingerprint": hashlib.sha256("\n".join(lines[:-1]).encode()).hexdigest()}


def parse_verdict(text, head, tree, gate):
    """state: no-blocker | blockers | stale (other gate, head or tree) | unreviewed (missing or malformed)."""
    rows = [r.strip() for r in (text or "").splitlines() if r.strip()]
    m = VERDICT.fullmatch(rows[0]) if rows else None
    if not m:
        return {"state": "unreviewed", "findings": []}
    if (m.group(1), m.group(2), m.group(3)) != (gate, head, tree):
        return {"state": "stale", "findings": []}
    parsed = [FINDING.fullmatch(r) for r in rows[1:]]
    if not all(parsed):
        return {"state": "unreviewed", "findings": []}
    findings = [dict(zip(("id", "severity", "source", "detail"), f.groups())) for f in parsed]
    if m.group(4) == "NO-BLOCKER":
        return {"state": "no-blocker" if not findings else "unreviewed", "findings": []}
    if int(m.group(5)) == 0 or int(m.group(5)) != len(findings):
        return {"state": "unreviewed", "findings": []}
    return {"state": "blockers", "findings": findings}


def reconcile(verdict_state, worker):
    """worker must be exactly 'yes' or 'no'. Disagreement is never resolved here."""
    if worker not in ("yes", "no"):
        raise ValueError(f"worker disposition must be 'yes' or 'no', got {worker!r}")
    if verdict_state not in ("no-blocker", "blockers"):
        return "unreviewed"
    if (verdict_state == "no-blocker") != (worker == "yes"):
        return "needs-human"
    return "reviewed-yes" if worker == "yes" else "reviewed-no"


def gate_settings(layers, gate):
    """layers: dicts from global to narrowest, each {gate: {key: value}}; narrower wins per key."""
    if gate not in GATES:
        raise ValueError(f"unknown gate {gate!r}")
    out = dict(DEFAULTS)
    for layer in layers:
        out.update(layer.get(gate, {}))
    return out


def should_send(fingerprint, sent):
    return fingerprint not in sent


def watch_step(record, now, state, worker=None):
    """One watcher tick. A verdict closes it unless it disagrees with the worker and no human escalation
    is recorded (record["escalated"]); stale/unreviewed replies keep waiting."""
    if state in ("no-blocker", "blockers"):
        if worker is not None and reconcile(state, worker) == "needs-human" and not record.get("escalated"):
            return {"action": "escalate", "state": "needs-human"}
        return {"action": "close", "state": state}
    if now <= record["sent_at"] + record["deadline_h"] * 3600:
        return {"action": "wait"}
    if record["retries"] < DEFAULTS["retries"]:
        return {"action": "retry"}
    return {"action": "tell-thomas", "state": "unreviewed"}


def value_summary(rows):
    out = {}
    for r in rows:
        s = out.setdefault(r["gate"], {"requests": 0, "blockers": 0, "tests_missed": 0,
                                       "false_positives": 0, "unreviewed": 0, "_lat": []})
        s["requests"] += 1
        if r["state"] == "blockers":
            s["blockers"] += 1
            if r.get("confirmed") is False:
                s["false_positives"] += 1
            if r.get("confirmed") and r.get("tests_green"):
                s["tests_missed"] += 1
        elif r["state"] in ("unreviewed", "stale"):
            s["unreviewed"] += 1
        if "latency_s" in r:
            s["_lat"].append(r["latency_s"])
    for s in out.values():
        lat = s.pop("_lat")
        s["median_latency_s"] = statistics.median(lat) if lat else None
    return out
