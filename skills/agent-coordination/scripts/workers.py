"""Worker adapters over the supported non-interactive CLIs; they build commands, run them through an
injectable runner and turn output into task events. They never attach to, interrupt or archive a
running interactive session: a session is resumed only when the task record says this layer owns it.
"""
import hashlib
import copy
import json
import subprocess
import os
import signal
import math
import re
from datetime import datetime, timezone
from pathlib import Path

# The worker's final answer; a ready claim still needs the verifier (tasks.MOVES).
REPORT_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["status", "summary", "commit", "tests", "need", "action", "target"],
    "properties": {
        "status": {"enum": ["running", "blocked", "ready"]},
        "summary": {"type": "string"}, "commit": {"type": "string"},
        "tests": {"type": "string"}, "need": {"type": "string"},
        # For a blocked report: the exact action and target the user would approve.
        "action": {"type": "string"}, "target": {"type": "string"},
        # Present for a bound task. The reducer rejects an active result unless every value
        # echoes its current task/deliverable tuple.
        "task_id": {"type": "string"}, "deliverable_id": {"type": "string"},
        "revision": {"type": "integer"}, "contract_digest": {"type": "string"},
        "next_action": {"type": "string"}, "packet_sha256": {"type": "string"},
        "final_diff_digest": {"type": "string"},
        "completion_report": {"type": "object"},
        "verifier_report": {"type": "object"},
        "artifact_kind": {"type": "string"}, "artifact_ref": {"type": "string"},
        "result": {"type": "string"}, "remaining": {"type": "array", "items": {"type": "string"}},
        "next_owner": {"type": "string"},
        "decision_source_ref": {"type": "string"},
        "material_facts": {"type": "array", "items": {"type": "object",
            "additionalProperties": False, "required": ["fact", "source_ref", "evidence_level"],
            "properties": {"fact": {"type": "string"}, "source_ref": {"type": "string"},
                "evidence_level": {"enum": ["reported", "performed", "independently_verified", "unverified"]}}}},
    },
}


def codex_report_schema():
    """Strict wire schema; keep binding fields typed and present.

    Structured Outputs requires closed objects with every property required.
    The two evidence reports contain task-defined dictionaries, so transport them
    as JSON strings and decode them before the existing evidence checks.
    Claude's report schema and the reducer's object contract remain unchanged.
    """
    schema = copy.deepcopy(REPORT_SCHEMA)
    properties = schema["properties"]
    properties["status"]["type"] = "string"
    properties["material_facts"]["items"]["properties"]["evidence_level"]["type"] = "string"
    # A scoped communication task can have no acceptance packet. Its exact
    # current_task_binding has packet_sha256=None; packet-bound tasks still
    # require their exact hash in the unchanged reducer.
    binding = {"task_id", "deliverable_id", "revision", "contract_digest",
               "next_action", "decision_source_ref"}
    for name, field in properties.items():
        if name in ("completion_report", "verifier_report"):
            properties[name] = {"type": ["string", "null"],
                                "description": "JSON-encoded report object; null when not applicable."}
        elif name not in schema["required"] and name not in binding:
            field["type"] = [field["type"], "null"]
    schema["required"] = list(properties)
    return schema


class Claude:
    kind = "claude"

    def __init__(self, model=None, effort=None, max_cost_usd=None, *, settings=None, max_turns=None,
                 name=None, mcp_config=None):
        # A worker has no one to approve a prompt, so it runs in bypassPermissions; the guard settings
        # (deny rules + PreToolUse hook) are what stop release, production and self-modifying calls.
        self.model = model
        self.effort, self.max_cost_usd = effort, max_cost_usd
        self.settings, self.max_turns, self.name = settings, max_turns, name
        self.mcp_config = mcp_config or '{"mcpServers":{}}'

    def command(self, *, session_id, resume):
        """`--session-id` fixes the id before launch, so an interrupted launch can be found later.
        The prompt goes on stdin (`run(input=...)`), never in argv, where `ps` would show it."""
        _selection(self.model, self.effort, "claude")
        if not self.settings:
            raise ValueError("worker guard settings required: bypassPermissions without them runs anything")
        argv = ["claude", "-p", "--output-format", "stream-json", "--verbose",
                "--json-schema", json.dumps(REPORT_SCHEMA),
                "--permission-mode", "bypassPermissions", "--settings", str(self.settings),
                # Only the servers named here: a worker never inherits the user's connectors or data tools.
                "--strict-mcp-config", "--mcp-config", self.mcp_config]
        argv += ["--resume", session_id] if resume else ["--session-id", session_id]
        argv += ["--model", self.model, "--effort", self.effort]
        if self.max_turns is not None:
            if type(self.max_turns) is not int or self.max_turns <= 0:
                raise ValueError("positive turn limit required")
            argv += ["--max-turns", str(self.max_turns)]
        argv += ["--name", self.name] if self.name else []
        if self.max_cost_usd is not None:
            if type(self.max_cost_usd) not in (int, float) or not math.isfinite(self.max_cost_usd) or self.max_cost_usd <= 0:
                raise ValueError("positive cost limit required")
            argv += ["--max-budget-usd", str(self.max_cost_usd)]
        return argv

    def parse(self, stdout):
        rows = _rows(stdout)
        out = next((x for x in reversed(rows) if x.get("type") == "result" or "structured_output" in x), {})
        sid = out.get("session_id") or next((x.get("session_id") for x in rows if x.get("session_id")), None)
        return {"session_id": sid, "error": bool(out.get("is_error")) or not out,
                "report": out.get("structured_output"), "execution": _metadata(rows)}

    @staticmethod
    def launched(session_id, receipt=None):
        """Only a supported output/inventory receipt proves launch; False means unverified."""
        return bool(isinstance(receipt, dict) and receipt.get("session_id") == session_id
                    and receipt.get("source") in ("cli-output", "cli-inventory"))


class Codex:
    kind = "codex"

    def __init__(self, sandbox="read-only", model=None, effort=None):
        self.sandbox, self.model = sandbox, model
        self.effort = effort

    @staticmethod
    def write_schema(schema_file):
        """Write the adapter's strict schema to the caller's task-owned file."""
        Path(schema_file).write_text(json.dumps(codex_report_schema()) + "\n")

    def command(self, prompt, *, cwd, schema_file, session_id=None):
        """The thread id is known only after start, so an interrupted fresh launch stays uncertain."""
        # The user's config can load connectors, plugins and data tools; a worker never inherits them
        # (auth still comes from the Codex home). The model is passed per call instead.
        _selection(self.model, self.effort, "codex")
        argv = ["codex", "exec", "--json", "--ignore-user-config", "-C", str(cwd), "-s", self.sandbox,
                "--output-schema", str(schema_file)]
        argv += ["-m", self.model, "-c", "model_reasoning_effort=" + json.dumps(self.effort)]
        return argv + (["resume", session_id, prompt] if session_id else [prompt])

    def parse(self, stdout, stderr=""):
        session_id, text, error = None, None, False
        rows = _rows(stdout)
        diagnostics = []
        for e in rows:
            session_id = e.get("thread_id") or session_id
            item = e.get("item") or {}
            if e.get("type") == "item.completed" and item.get("type") == "agent_message":
                text = item.get("text")
            error = error or e.get("type") in ("error", "turn.failed")
            if item.get("type") == "error":
                diagnostics.append(item.get("message", ""))
        try:
            report = json.loads(text) if text else None
            if isinstance(report, dict):
                for key in ("completion_report", "verifier_report"):
                    if isinstance(report.get(key), str):
                        report[key] = json.loads(report[key])
                        if not isinstance(report[key], dict):
                            raise ValueError("evidence report must decode to an object")
        except ValueError:
            report = None
            error = True
        # CLI warnings also use item.error. Retain them; only a completed turn with a
        # valid report distinguishes a nonterminal diagnostic from an unresolved failure.
        if diagnostics and not (report and any(x.get("type") == "turn.completed" for x in rows)):
            error = True
        metadata = _metadata(rows)
        metadata["diagnostics"] = diagnostics
        for line in stderr.splitlines():
            if 'event.name="codex.conversation_starts"' not in line:
                continue
            fields = {key: quoted or bare for key, quoted, bare in re.findall(
                r'\b(model|reasoning_effort|conversation\.id)=(?:"([^"]*)"|(\S+))', line)}
            if not session_id or fields.get("conversation.id") != session_id:
                continue
            observed = _metadata([{"type": "system", "model": fields.get("model"),
                                   "reasoning_effort": fields.get("reasoning_effort")}])
            # The runtime start for this exact conversation is root evidence of the primary model.
            _add(metadata["models"], observed["models"])
            _add(metadata["primary_models"], observed["models"])
            effort = observed["effective_effort"]
            if effort is not None:
                prior = metadata["effective_effort"]
                if prior is not None and prior != effort:
                    metadata["conflicting_efforts"] = sorted({prior, effort})
                    metadata["effective_effort"] = None
                elif not metadata.get("conflicting_efforts"):
                    metadata["effective_effort"] = effort
            if "cli-runtime-start" not in metadata["metadata_sources"]:
                metadata["metadata_sources"].append("cli-runtime-start")
        return {"session_id": session_id, "error": error, "report": report, "execution": _roles(metadata)}


def _selection(model, effort, provider):
    supported = {"low", "medium", "high", "xhigh", "max"}
    if provider == "codex":
        supported.add("ultra")
    if not isinstance(model, str) or not model.strip() or model.startswith('-') or effort not in supported:
        raise ValueError("explicit supported model and effort required; select from the current catalog")


def _rows(stdout):
    try:
        value = json.loads(stdout)
        values = value if isinstance(value, list) else [value]
    except ValueError:
        values = []
        for line in stdout.splitlines():
            try:
                values.append(json.loads(line))
            except ValueError:
                continue  # A timeout can end midway through the last event.
    return [x for x in values if isinstance(x, dict)]


def _add(values, items):
    for item in items:
        if item not in values:
            values.append(item)


def _roles(evidence):
    """Primary = root runtime rows; auxiliary = every other observed model. Without root rows the
    aggregate usage list stays unattributed (`usage-only`), never promoted to a primary claim."""
    primary = evidence["primary_models"]
    evidence["auxiliary_models"] = [m for m in evidence["models"] if m not in primary] if primary else []
    evidence["model_attribution"] = "root-rows" if primary else "usage-only" if evidence["models"] else "none"
    return evidence


def _metadata(rows):
    evidence = {"models": [], "primary_models": [], "effective_effort": None, "usage": [], "model_usage": {},
                "metadata_sources": []}
    efforts = set()
    for row in rows:
        kind = row.get("type")
        message = row.get("message") if isinstance(row.get("message"), dict) else {}
        if kind == "assistant" and isinstance(message.get("model"), str):
            # A row inside a tool call (parent_tool_use_id set) is auxiliary, never the primary run.
            _add(evidence["models"], [message["model"]])
            if not row.get("parent_tool_use_id"):
                _add(evidence["primary_models"], [message["model"]])
            continue
        if kind not in ("system", "thread.started", "turn.started", "turn.completed", "result"):
            continue
        models = [row["model"]] if isinstance(row.get("model"), str) else []
        if kind != "result" and not row.get("parent_tool_use_id"):
            _add(evidence["primary_models"], models)
        if isinstance(row.get("modelUsage"), dict):
            models += list(row["modelUsage"])
            evidence["model_usage"].update(row["modelUsage"])
        _add(evidence["models"], models)
        # Never recover effective settings from assistant text or requested argv.
        for key in ("effort", "reasoning_effort"):
            if row.get(key) in ("low", "medium", "high", "xhigh", "max", "ultra"):
                efforts.add(row[key])
        if isinstance(row.get("usage"), dict):
            evidence["usage"].append(row["usage"])
        if models or any(key in row for key in ("effort", "reasoning_effort", "usage")):
            evidence["metadata_sources"].append(kind)
        if "total_cost_usd" in row:
            evidence["reported_cost_usd"] = row["total_cost_usd"]
    if len(efforts) == 1:
        evidence["effective_effort"] = next(iter(efforts))
    elif efforts:
        evidence["conflicting_efforts"] = sorted(efforts)
    return _roles(evidence)


class RunResult:
    """Retains diagnostics while preserving legacy `(state, stdout)` unpacking."""
    def __init__(self, state, stdout, stderr, returncode, pid, started, finished):
        self.state, self.stdout, self.stderr = state, stdout, stderr
        self.returncode, self.pid = returncode, pid
        self.started_at_utc, self.finished_at_utc = started, finished

    def __iter__(self):
        return iter((self.state, self.stdout))

    def __getitem__(self, index):
        return (self.state, self.stdout)[index]


def _owned_process(argv, *, cwd, capture_output, text, timeout, stdin=None, input=None):
    """Time bounds affect only this newly created process group, never an existing session."""
    p = subprocess.Popen(argv, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=text,
                         stdin=subprocess.PIPE if input is not None else stdin, start_new_session=True)
    try:
        stdout, stderr = p.communicate(input=input, timeout=timeout)
    except subprocess.TimeoutExpired as error:
        try:
            os.killpg(p.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            stdout, stderr = p.communicate(timeout=2)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(p.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            stdout, stderr = p.communicate()
        error.output, error.stderr, error.pid = stdout, stderr, p.pid
        error.returncode = p.returncode
        raise
    result = subprocess.CompletedProcess(argv, p.returncode, stdout, stderr)
    result.pid = p.pid
    return result


def run(argv, *, cwd, timeout, runner=None, input=None):
    """Preserve stdout/stderr and identity; timeout remains uncertain even after local exit."""
    if type(timeout) not in (int, float) or not math.isfinite(timeout) or not 0 < timeout <= 3600:
        raise ValueError("positive timeout required")
    started = datetime.now(timezone.utc).isoformat()
    def result(state, stdout="", stderr="", returncode=None, pid=None):
        def decoded(value):
            return value.decode(errors="replace") if isinstance(value, bytes) else (value or "")
        return RunResult(state, decoded(stdout), decoded(stderr), returncode, pid,
                         started, datetime.now(timezone.utc).isoformat())
    try:
        # An open stdin makes a CLI wait for piped input until the timeout, so a worker gets
        # either its prompt (then EOF) or nothing.
        stdin = {"input": input} if input is not None else {"stdin": subprocess.DEVNULL}
        p = (runner or _owned_process)(argv, cwd=cwd, capture_output=True, text=True,
                                       timeout=timeout, **stdin)
    except FileNotFoundError as error:
        return result("unavailable", stderr=str(error))
    except subprocess.TimeoutExpired as error:
        return result("uncertain", error.output, error.stderr,
                      getattr(error, "returncode", None), getattr(error, "pid", None))
    return result("done" if p.returncode == 0 else "failed", p.stdout, p.stderr,
                  p.returncode, getattr(p, "pid", None))


def events(task_id, dispatch_id, parsed, started, finished):
    """Task events from one parsed run, stamped at launch and at result; ids derive from content,
    so a replayed result is a duplicate."""
    sid = parsed["session_id"]
    out = [{"id": f"{dispatch_id}:dispatched", "task": task_id, "ts": started, "source": "adapter",
            "kind": "dispatched", "data": {"session_id": sid}}]
    rep = parsed["report"]
    if parsed["error"] or not rep:
        out.append({"id": f"{dispatch_id}:no-report", "task": task_id, "ts": finished, "source": "adapter", "kind": "idle"})
        return out
    digest = hashlib.sha256(json.dumps(rep, sort_keys=True).encode()).hexdigest()[:16]
    data = {k: rep.get(k) if rep.get(k) is not None else None for k in (
        "commit", "tests", "summary", "need", "action", "target", "task_id",
        "deliverable_id", "revision", "contract_digest", "next_action", "packet_sha256",
        "final_diff_digest", "completion_report", "verifier_report", "artifact_kind",
        "artifact_ref", "result", "remaining", "next_owner", "decision_source_ref", "material_facts")}
    out.append({"id": f"{dispatch_id}:{sid}:{digest}", "task": task_id, "ts": finished, "source": "worker",
                "kind": rep["status"], "data": data})
    return out
