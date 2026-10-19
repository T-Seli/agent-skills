#!/usr/bin/env python3
"""PreToolUse guard for delegated workers (`delegate.py` passes it via --settings).

Workers run in bypassPermissions, so this hook is what stops release, production and
self-modifying actions. Deny rules in worker-settings.json are the cheap first layer;
this hook also sees compound commands and `bash -c`/`python -c` wrappers.
Fail-closed: unreadable input or any internal error blocks the call (exit 2), because a
command hook that exits with any other non-zero code does not block.
"""
import json
import os
import re
import shlex
import sys
from pathlib import Path

HOME = Path(os.environ.get("HOME", str(Path.home())))
TELL = "Blocked by the worker guard: {}. Do not retry or work around it; report it to your parent as a blocker."

PREFIX = {"sudo", "env", "nohup", "time", "exec", "command", "nice", "caffeinate", "xargs", "timeout"}
SHELLS = {"bash", "sh", "zsh", "dash", "fish"}
INTERPRETERS = {"python", "python3", "node", "ruby", "perl"}
REMOTE = {"ssh", "scp", "sftp", "mosh", "telnet"}
DATABASES = {"psql", "pg_restore", "dropdb", "createdb", "mysql", "mongosh", "mongo", "redis-cli", "sqlcmd"}
WRITERS = {"cp", "mv", "ln", "rm", "rmdir", "tee", "touch", "chmod", "chown", "install", "rsync",
           "truncate", "dd", "unlink", "mkdir", "patch"}
DEPLOY_VERBS = {
    "serverless": None, "sls": None, "sam": None, "cdk": None, "vercel": None, "netlify": None,
    "firebase": None, "fly": None, "flyctl": None, "eb": None, "wrangler": None,
    "terraform": {"apply", "destroy", "import"}, "pulumi": {"up", "destroy", "refresh"},
    "kubectl": {"apply", "delete", "rollout", "scale", "set", "patch", "edit", "create", "replace"},
    "helm": {"install", "upgrade", "uninstall", "rollback"}, "docker": {"push"},
}
AWS_READ = {"describe", "get", "list", "head", "lookup", "filter", "search", "scan", "query",
            "select", "tail", "validate", "estimate", "simulate", "test", "ls", "wait", "help"}
AWS_VALUE_OPTIONS = {"--region", "--profile", "--output", "--endpoint-url", "--query", "--color",
                     "--ca-bundle", "--cli-read-timeout", "--cli-connect-timeout"}
GIT_CONFIG_READ = {"--get", "--get-all", "--get-regexp", "--list", "-l", "--show-origin", "--get-urlmatch"}
SECRET = re.compile(r"(^|[\s'\"=/<])\.env(\.(local|prod|production|development|dev|staging|test))?(?=$|[\s'\";|&)>])"
                    r"|\.ssh/id_|\.aws/credentials|\.pem\b")
PROJECT_PROTECTED = re.compile(r"(^|/)(\.git/(config|hooks)(/|$)|\.claude/(settings[^/]*\.json|hooks)(/|$)|\.mcp\.json$)")
SHELL_RC = {".zshrc", ".zprofile", ".zshenv", ".bashrc", ".bash_profile", ".profile"}


def protected_roots():
    roots = [HOME / ".claude", HOME / ".codex", HOME / ".agents", HOME / ".config" / "agent-skills",
             HOME / ".ssh", HOME / ".aws", HOME / "Library" / "LaunchAgents"]
    skills = HOME / ".claude" / "skills"
    if skills.is_dir():
        # The installed release behind the skill links: editing it ships unreviewed skills.
        roots += [link.resolve().parents[1] for link in skills.iterdir() if link.is_symlink()]
    return [r.resolve() for r in roots]


def protected(path, cwd):
    p = Path(os.path.expanduser(str(path)))
    p = (p if p.is_absolute() else Path(cwd) / p).resolve()
    if p.parent == HOME.resolve() and p.name in SHELL_RC:
        return True
    if PROJECT_PROTECTED.search(p.as_posix()):
        return True
    return any(p == r or r in p.parents for r in protected_roots())


def words(segment):
    try:
        return shlex.split(segment, posix=True)
    except ValueError:  # unbalanced quotes (a separator split a quoted string): still inspect the words
        return [w.strip("'\"") for w in segment.split()]


def segments(text):
    return [s for s in re.split(r"\|\||&&|[;|&\n`()]|\$\(", text) if s.strip()]


def command_words(tokens):
    i = 0
    while i < len(tokens) and (re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=.*|\d+[smhd]?", tokens[i]) or
                               os.path.basename(tokens[i]) in PREFIX or tokens[i].startswith("-")):
        i += 1
    return tokens[i:]


def git_subcommand(args):
    i = 0
    while i < len(args) and args[i].startswith("-"):
        i += 2 if args[i] in ("-C", "-c") else 1
    return args[i:]


def aws_reason(args):
    rest, skip = [], False
    for a in args:
        if skip or a.startswith("-"):
            skip = a in AWS_VALUE_OPTIONS
            continue
        rest.append(a)
    if len(rest) < 2:
        return None
    service, op = rest[0], rest[1]
    if service == "s3":
        if op in ("rm", "mb", "rb") or (op in ("cp", "mv", "sync") and any(a.startswith("s3://") for a in rest[3:])):
            return f"aws s3 {op} writes to S3"
        return None
    verb = op.split("-")
    verb = verb[1] if verb[0] == "batch" and len(verb) > 1 else verb[0]
    return None if verb in AWS_READ else f"aws {service} {op} changes cloud resources"


def check_segment(segment, cwd, depth):
    tokens = command_words(words(segment))
    if not tokens:
        return None
    cmd, args = os.path.basename(tokens[0]), tokens[1:]
    if cmd in SHELLS or cmd == "eval":
        inner = args[args.index("-c") + 1] if "-c" in args[:-1] else " ".join(args) if cmd == "eval" else ""
        return check_bash(inner, cwd, depth + 1) if inner else None
    if cmd in INTERPRETERS and any(a in ("-c", "-e") for a in args):
        return check_text(" ".join(args), code=True)
    if cmd == "git":
        sub = git_subcommand(args)
        if sub[:1] == ["push"]:
            return "git push publishes commits"
        if sub[:1] == ["config"] and not GIT_CONFIG_READ & set(sub):
            return "git config changes repository or user configuration"
        if sub[:1] == ["remote"] and sub[1:2] and sub[1] in ("add", "set-url", "remove", "rename"):
            return "git remote changes repository configuration"
    if cmd == "gh":
        if args[:2] in (["pr", "create"], ["pr", "merge"]) or (
                args[:1] == ["release"] and args[1:2] not in (["view"], ["list"], ["download"])):
            return f"gh {' '.join(args[:2])} publishes or merges"
        if args[:1] == ["api"] and (re.search(r"(-X|--method)\s*(POST|PUT|PATCH|DELETE)", segment, re.I)
                                    or re.search(r"\s(-f|-F|--field|--raw-field|--input)\b", segment)):
            return "gh api request changes GitHub state"
    if "deploy" in cmd or (cmd in ("npm", "yarn", "pnpm", "bun", "make") and any("deploy" in a for a in args)):
        return "deploy commands are release actions"
    if cmd in DEPLOY_VERBS:
        verbs = DEPLOY_VERBS[cmd]
        if verbs is None or (args and args[0] in verbs):
            return f"{cmd} {' '.join(args[:1])} changes deployed infrastructure"
    if cmd in REMOTE or (cmd == "rsync" and any(re.match(r"^[^/\s]*[^/\s:]:", a) for a in args)):
        return f"{cmd} opens a remote shell or copy"
    if cmd in DATABASES:
        return f"{cmd} connects to a database; use a read-only data tool instead"
    if cmd == "aws":
        return aws_reason(args)
    if cmd in ("claude", "codex") and args[:1] not in (["--version"], ["agents"]):
        return f"{cmd} launches an agent outside delegate.py; use delegate.py start"
    if cmd in ("crontab", "launchctl") or (cmd == "defaults" and args[:1] == ["write"]):
        return f"{cmd} changes scheduled or system configuration"
    writes = cmd in WRITERS or (cmd in ("sed", "perl") and any(a.startswith("-i") for a in args)) or ">" in segment
    if writes:
        targets = [a for a in args if not a.startswith("-")] + re.findall(r">>?\s*(\S+)", segment)
        if any(protected(t, cwd) for t in targets):
            return "writes to skills, settings, hooks or git configuration are not allowed"
    return None


def check_text(text, code=False):
    if re.search(r"--dangerously-skip-permissions\b", text):
        return "bypass flags are not allowed inside a worker"
    # Inside interpreter code a command is only text; in a shell command the segment check sees it.
    if code and re.search(r"\bgit(\s+(-C\s+\S+|-c\s+\S+|--\S+))*\s+push\b", text):
        return "git push publishes commits"
    if SECRET.search(text):
        return "reading secrets files is not allowed"
    return None


def check_bash(command, cwd, depth=0):
    if depth > 3:
        return "nested shell wrappers are too deep to inspect"
    interpreted = re.search(r"\b(python3?|node|ruby|perl)\b[^|;&]*\s-[ce]\b", command)
    reason = check_text(command, code=bool(interpreted))
    for segment in segments(command):
        tokens = command_words(words(segment))
        if tokens[:1] in (["cd"], ["pushd"]) and tokens[1:2]:
            # A later write in the same command lands relative to the new directory.
            cwd = str(Path(cwd) / os.path.expanduser(tokens[1]))
            continue
        reason = reason or check_segment(segment, cwd, depth)
    return reason


def check(event):
    tool, data = event["tool_name"], event.get("tool_input") or {}
    cwd = event.get("cwd") or os.getcwd()
    if tool == "Bash" or isinstance(data.get("command"), str):  # Bash, Monitor and any shell-running tool
        return check_bash(data["command"], cwd)
    if tool in ("Write", "Edit", "MultiEdit", "NotebookEdit"):
        path = data.get("file_path") or data.get("notebook_path")
        if protected(path, cwd):
            return f"editing {path} is not allowed"
    if tool == "Read" and SECRET.search(" " + str(data.get("file_path", ""))):
        return "reading secrets files is not allowed"
    return None


def main():
    try:
        reason = check(json.load(sys.stdin))
    except Exception as error:  # fail closed: a broken guard must not let the call through
        reason = f"the guard could not inspect this call ({type(error).__name__})"
    if reason:
        print(TELL.format(reason), file=sys.stderr)
        sys.exit(2)
    sys.exit(0)


if __name__ == "__main__":
    main()
