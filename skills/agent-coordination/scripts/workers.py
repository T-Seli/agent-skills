"""Worker adapters over the supported non-interactive CLIs; they build commands, run them through an
injectable runner and turn output into task events. They never attach to, interrupt or archive a
running interactive session: a session is resumed only when the task record says this layer owns it.
"""
import hashlib
import json
import subprocess
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
    },
}


class Claude:
    kind = "claude"

    def __init__(self, model=None):
        # --allowedTools is a permission grant, not a sandbox. This adapter grants none.
        self.model = model

    def command(self, prompt, *, session_id, resume):
        """`--session-id` fixes the id before launch, so an interrupted launch can be found later."""
        argv = ["claude", "-p", prompt, "--output-format", "json", "--json-schema", json.dumps(REPORT_SCHEMA),
                "--permission-mode", "dontAsk",
                # Only the servers named here: a worker never inherits the user's connectors or data tools.
                "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}']
        argv += ["--resume", session_id] if resume else ["--session-id", session_id]
        return argv + (["--model", self.model] if self.model else [])

    def parse(self, stdout):
        out = json.loads(stdout)
        return {"session_id": out.get("session_id"), "error": bool(out.get("is_error")),
                "report": out.get("structured_output")}

    @staticmethod
    def launched(session_id, projects=Path("~/.claude/projects").expanduser()):
        """True when a transcript for this id exists: the launch happened, whatever its outcome."""
        return any(projects.glob(f"*/{session_id}.jsonl"))


class Codex:
    kind = "codex"

    def __init__(self, sandbox="read-only", model=None):
        self.sandbox, self.model = sandbox, model

    def command(self, prompt, *, cwd, schema_file, session_id=None):
        """The thread id is known only after start, so an interrupted fresh launch stays uncertain."""
        # The user's config can load connectors, plugins and data tools; a worker never inherits them
        # (auth still comes from the Codex home). The model is passed per call instead.
        argv = ["codex", "exec", "--json", "--ignore-user-config", "-C", str(cwd), "-s", self.sandbox,
                "--output-schema", str(schema_file)]
        argv += ["-m", self.model] if self.model else []
        return argv + (["resume", session_id, prompt] if session_id else [prompt])

    def parse(self, stdout):
        session_id, text, error = None, None, False
        for line in stdout.splitlines():
            try:
                e = json.loads(line)
            except ValueError:
                continue
            session_id = e.get("thread_id") or session_id
            item = e.get("item") or {}
            if e.get("type") == "item.completed" and item.get("type") == "agent_message":
                text = item.get("text")
            error = error or e.get("type") in ("error", "turn.failed")
        try:
            report = json.loads(text) if text else None
        except ValueError:
            report = None
        return {"session_id": session_id, "error": error, "report": report}


def run(argv, *, cwd, timeout, runner=subprocess.run):
    """Returns (state, stdout): done, failed, unavailable (never started) or uncertain (may have acted)."""
    try:
        # An open stdin makes a CLI wait for piped input until the timeout; workers get none.
        p = runner(argv, cwd=cwd, capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL)
    except FileNotFoundError:
        return "unavailable", ""
    except subprocess.TimeoutExpired:
        return "uncertain", ""
    return ("done" if p.returncode == 0 else "failed"), p.stdout


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
    data = {k: rep.get(k) or None for k in ("commit", "tests", "summary", "need", "action", "target")}
    out.append({"id": f"{dispatch_id}:{sid}:{digest}", "task": task_id, "ts": finished, "source": "worker",
                "kind": rep["status"], "data": data})
    return out
