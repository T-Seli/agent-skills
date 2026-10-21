#!/usr/bin/env python3
"""PreToolUse guard for delegated workers (`delegate.py` passes it via --settings).

Workers run in bypassPermissions, so this hook is what stops release, production and
self-modifying actions. Deny rules in worker-settings.json are the cheap first layer;
this hook also sees compound commands and `bash -c`/`python -c` wrappers.
Fail-closed: unreadable input or any internal error blocks the call (exit 2), because a
command hook that exits with any other non-zero code does not block.
"""
import fnmatch
import json
import os
import re
import shlex
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

HOME = Path(os.environ.get("HOME", str(Path.home())))
CONFIG = Path(os.environ.get("AGENT_SKILLS_CONFIG", str(HOME / ".config" / "agent-skills" / "workers.json")))
TELL = "Blocked by the worker guard: {}. Do not retry or work around it; report it to your parent as a blocker."

PREFIX = {"sudo", "env", "nohup", "time", "exec", "command", "nice", "caffeinate", "xargs", "timeout",
          "if", "then", "elif", "else", "while", "until", "do", "!", "{"}
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
GH_READ = {"view", "list", "diff", "checks", "status", "download", "watch", "checkout"}
PUSH_OPTS = {"-u", "--set-upstream", "--no-verify", "-q", "--quiet", "-v", "--verbose", "--porcelain", "--progress"}
REDIRECT = re.compile(r"^(\d*|&)?(>>?\|?|<)(&?\S*)?$")  # 2>&1, >out, > out, 2>/dev/null, <in
DEPLOY_PATH = re.compile(r"(^|/)deploy(/|[\w.-]*\.(sh|ts|js|mjs|py)$)")  # src/deploy/x.sh, scripts/deploy.sh
RUNNERS = {"npx", "ts-node", "tsx"}
SSH_VALUE_OPTIONS = set("-b -c -D -E -e -F -I -i -J -L -l -m -O -o -p -Q -R -S -W -w".split())
METADATA = {"ls", "test", "[", "[[", "stat"}  # see that a secrets file exists without reading it
READERS = {"cat", "less", "more", "head", "tail", "grep", "egrep", "rg", "sed", "awk", "source", ".", "cp",
           "base64", "xxd", "od", "hexdump", "strings", "sort", "cut", "diff", "jq"}
SECRET = re.compile(r"(^|[\s'\"=/<])\.env(\.(local|prod|production|development|dev|staging|test))?(?=$|[\s'\";|&)>])"
                    r"|\.pem\b")
KEY_DIRS = re.compile(r"(^|[\s'\"=:/<])\.(ssh|aws)(?=$|[/\s'\";|&)>])")  # anything under ~/.ssh or ~/.aws
HEREDOC = re.compile(r"<<(-?)[ \t]*(['\"]?)\\?([\w.@-]+)\2")
PROJECT_PROTECTED = re.compile(r"(^|/)(\.git/(config|hooks)(/|$)|\.claude/(settings[^/]*\.json|hooks)(/|$)|\.mcp\.json$)")
SHELL_RC = {".zshrc", ".zprofile", ".zshenv", ".bashrc", ".bash_profile", ".profile"}


def protected_roots():
    roots = [HOME / ".claude", HOME / ".codex", HOME / ".agents", HOME / ".config" / "agent-skills",
             HOME / ".gitconfig", HOME / ".config" / "git",
             HOME / ".ssh", HOME / ".aws", HOME / "Library" / "LaunchAgents"]
    skills = HOME / ".claude" / "skills"
    if skills.is_dir():
        # The installed release behind the skill links: editing it ships unreviewed skills.
        roots += [link.resolve().parents[1] for link in skills.iterdir() if link.is_symlink()]
    return [r.resolve() for r in roots]


def protected(path, cwd):
    p = Path(os.path.expanduser(os.path.expandvars(str(path))))
    p = (p if p.is_absolute() else Path(cwd) / p).resolve()
    if p.parent == HOME.resolve() and p.name in SHELL_RC:
        return True
    if PROJECT_PROTECTED.search(p.as_posix()):
        return True
    return any(p == r or r in p.parents for r in protected_roots())


def git_out(cwd, *args):
    return subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True, check=True).stdout.strip()


def origin_repo(cwd):
    """owner/name of the origin remote, from an https or ssh URL."""
    m = re.search(r"[:/]([^/:]+/[^/]+?)(\.git)?/?$", git_out(cwd, "remote", "get-url", "origin"))
    return m and m.group(1)


def protected_branches(cwd):
    """main, master and the branches the repo's CLAUDE.md names as base, release or protected."""
    names, claude = {"main", "master"}, Path(git_out(cwd, "rev-parse", "--show-toplevel")) / "CLAUDE.md"
    for line in claude.read_text(encoding="utf-8").splitlines() if claude.is_file() else []:
        if re.match(r"\s*-\s*(Base branch|Release branch|Protected):", line):
            names |= set(re.findall(r"`([^`\s]+)`", line))
    return names


def release_grant(cwd):
    """The grant delegate.py put in this worker's environment, while unexpired and for this repo; else None.
    The hook inherits the worker process's environment, which the worker's own commands cannot change."""
    if "AGENT_SKILLS_GRANT" not in os.environ:
        return None
    try:
        grant = json.loads(os.environ["AGENT_SKILLS_GRANT"])
        expires = datetime.strptime(grant["expires"], "%Y-%m-%dT%H:%MZ").replace(tzinfo=timezone.utc)
        live = expires > datetime.now(timezone.utc) and (origin_repo(cwd) or "").lower() == grant["repo"].lower()
    except (KeyError, TypeError, ValueError, subprocess.CalledProcessError):
        return None
    return grant if live else None


def push_reason(args, cwd):
    """Sharing: push the task branch you are on. A release grant also allows pushing to its base."""
    i = 0
    while i < len(args) and args[i].startswith("-"):
        if args[i] == "-C":
            cwd = str(Path(cwd) / os.path.expanduser(args[i + 1]))
        i += 2 if args[i] in ("-C", "-c") else 1
    rest = without_redirects(args[i + 1:])
    if {a for a in rest if a.startswith("-")} - PUSH_OPTS:
        return "git push may not force, delete, mirror or push tags"
    refs = [a for a in rest if not a.startswith("-")]
    if len(refs) != 2 or refs[0] != "origin":
        return "name the remote and branch: git push -u origin <branch>"
    if subprocess.run(["git", "-C", str(cwd), "config", "--get-all", "remote.origin.push"], capture_output=True).stdout:
        return "remote.origin.push is configured, so this push would not land where it names"
    current = git_out(cwd, "rev-parse", "--abbrev-ref", "HEAD")
    src, _, dst = refs[1].partition(":")
    src = current if src == "HEAD" else src
    dst = (dst or src).removeprefix("refs/heads/")
    if not src or src.startswith("+"):
        return "git push may not force or delete a branch"
    grant = release_grant(cwd)
    if grant and dst == grant["base"]:
        return None
    if current == "HEAD" or src != current or dst != current:
        return "a worker pushes only the task branch it is on"
    if current in protected_branches(cwd):
        return f"{current} is a protected branch; pushing it is a release"
    return None


def without_redirects(tokens):
    """Drop shell redirections (and a detached redirect target) so they are not read as refspecs."""
    out, target = [], False
    for t in tokens:
        if target:
            target = False
        elif m := REDIRECT.match(t):
            target = not m.group(3)
        else:
            out.append(t)
    return out


def canonical(tokens):
    """For blocking: `npx npm`, npm aliases and options before `run` do not change which script runs."""
    if tokens and os.path.basename(tokens[0]) == "npx" and "npm" in tokens[1:4]:
        tokens = tokens[tokens.index("npm", 1):]
    if tokens and os.path.basename(tokens[0]) == "npm":
        for i, t in enumerate(tokens[1:], 1):
            if t in ("run", "run-script", "rum", "urn"):
                return ["npm", "run"] + tokens[i + 1:]
    return tokens


def matches(tokens, pattern):
    """For blocking: the command's leading words match the pattern's (npm forms folded; `*` is a wildcard)."""
    words, tokens = canonical(shlex.split(pattern)), canonical(tokens)
    return len(tokens) >= len(words) and all(fnmatch.fnmatchcase(t, w) for t, w in zip(tokens, words))


def granted(tokens, pattern):
    """For a grant: the exact leading words with `*` wildcards, no `..`, no npm --prefix/--workspace, and no repeat
    of an option the pattern pins (a second `--id` would retarget the command)."""
    words = shlex.split(pattern)
    pinned = {w.split("=")[0] for w in words if w.startswith("-")}
    elsewhere = {"--prefix", "-C", "--workspace", "-w"} if os.path.basename(tokens[0]) == "npm" else set()
    return (len(tokens) >= len(words) and all(fnmatch.fnmatchcase(t, w) for t, w in zip(tokens, words))
            and not any(".." in t for t in tokens)
            and not any(t.split("=")[0] in pinned for t in tokens[len(words):])
            and not any(t.split("=")[0] in elsewhere for t in tokens))


def release_commands():
    """Every command any repo's release config lists; each needs a grant wherever it is run from."""
    if not CONFIG.exists():
        return []
    repos = json.loads(CONFIG.read_text(encoding="utf-8")).get("release", {}).get("repos", {})
    return [c for r in repos.values() for t in r.get("targets", {}).values() for c in t.get("commands", [])]


def runs_deploy_script(tokens, cwd):
    """The command is, or runs through a shell or runner, a script from a deploy folder or named deploy*;
    relative script paths resolve against the current directory."""
    runner = os.path.basename(tokens[0]) in SHELLS | INTERPRETERS | RUNNERS
    paths = tokens[:1] + ([t for t in tokens[1:] if not t.startswith("-")] if runner else [])
    return any(DEPLOY_PATH.search(t) or (re.search(r"\.(sh|ts|js|mjs|py)$", t) and DEPLOY_PATH.search(str(Path(cwd) / t)))
               for t in paths)


def remote_hosts(cmd, args):
    if cmd == "ssh":
        i = 0
        while i < len(args) and args[i].startswith("-"):
            i += 2 if args[i] in SSH_VALUE_OPTIONS else 1
        return args[i:i + 1]
    return [a.split(":", 1)[0] for a in args if re.match(r"^[^/\s]*[^/\s:]:", a)]


def words(segment):
    return shlex.split(segment, posix=True)  # ValueError on bad quoting blocks the call


def scan(text, i=0, close=""):
    """Cut shell text into command segments on separators outside quotes; returns (segments, heredocs, end).

    A command substitution yields segments of its own and stands as `_` in the outer one. A heredoc
    body is cut out and returned with the segments from the command it feeds to the end of its line.
    """
    segments, heredocs, pending, buf, quote = [], [], [], "", ""
    while i < len(text):
        c, two = text[i], text[i:i + 2]
        if quote == "'":
            buf, quote = buf + c, "" if c == "'" else quote
        elif c == "\\":
            buf, i = buf + ("" if two == "\\\n" else two), i + 2
            continue
        elif c == close and not quote:
            break
        elif two == "$(" or c == "`":
            inner, docs, i = scan(text, i + len(two if c == "$" else c), ")" if c == "$" else "`")
            segments, heredocs, buf = segments + inner, heredocs + docs, buf + "_"
        elif c == '"' or (c == "'" and not quote):
            buf, quote = buf + c, "" if quote else c
        elif quote:
            buf += c
        elif c == "#" and buf[-1:] in ("", " ", "\t"):  # comment to end of line
            i = text.find("\n", i) if "\n" in text[i:] else len(text)
            continue
        elif text.startswith("<<<", i):
            buf, i = buf + "<<<", i + 3
            continue
        elif m := HEREDOC.match(text, i):
            pending.append((m.group(3), m.group(1), len(segments)))
            buf, i = buf + m.group(0), m.end()
            continue
        elif c in ";&|()\n" and not (c in "&|" and buf.endswith((">", "<")) or two == "&>"):  # not 2>&1, &>, >|
            segments.append(buf)
            buf = ""
            if c == "\n":
                for word, dash, start in pending:
                    end = re.compile("^%s%s$" % ("\t*" if dash else "", re.escape(word)), re.M).search(text, i + 1)
                    if not end:  # no terminator line: check the rest as commands
                        break
                    heredocs.append((text[i + 1:end.start()], segments[start:]))
                    i = end.end()
                pending = []
        else:
            buf += c
        i += 1
    if quote or (close and i >= len(text)):
        raise ValueError("unbalanced quotes or substitution")
    return [s for s in segments + [buf] if s.strip()], heredocs, i


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
    if service == "configure" and op not in ("list", "list-profiles"):
        return "aws configure reads or changes ~/.aws credentials"
    if service == "s3":
        if op in ("rm", "mb", "rb") or (op in ("cp", "mv", "sync") and any(a.startswith("s3://") for a in rest[3:])):
            return f"aws s3 {op} writes to S3"
        return None
    verb = op.split("-")
    verb = verb[1] if verb[0] == "batch" and len(verb) > 1 else verb[0]
    return None if verb in AWS_READ else f"aws {service} {op} changes cloud resources"


def check_segment(segment, cwd, depth):
    every = words(segment)
    tokens = command_words(every)
    cmd, args = (os.path.basename(tokens[0]), tokens[1:]) if tokens else ("", [])
    if re.search(r"--dangerously-skip-permissions\b", segment):
        return "bypass flags are not allowed inside a worker"
    # A secrets path as an argument reads the file; a quoted sentence that mentions one does not.
    if KEY_DIRS.search(segment) or cmd not in METADATA and any(
            SECRET.search(" " + w) and (cmd in READERS or not re.search(r"\s", w)) for w in every):
        return "reading secrets files is not allowed"
    if any(w.startswith("--approved") for w in every):
        return "only the attended session starts a release worker"
    if not tokens:
        return None
    grant = release_grant(cwd)
    if grant and cmd != "git" and any(granted(tokens, p) for p in grant.get("commands", [])):  # git goes through push_reason
        return write_reason(segment, cmd, args, cwd)  # a granted release command still may not write protected config
    if any(matches(tokens, p) for p in release_commands()):
        return "this repo's release config lists this command; it runs only under a release grant"
    if runs_deploy_script(tokens, cwd):
        return "deploy scripts are release actions"
    if cmd in SHELLS or cmd == "eval":
        inner = args[args.index("-c") + 1] if "-c" in args[:-1] else " ".join(args) if cmd == "eval" else ""
        return check_bash(inner, cwd, depth + 1) if inner else None
    if cmd in INTERPRETERS and any(a in ("-c", "-e") for a in args):
        return check_text(" ".join(args))
    if "GIT_CONFIG" in segment or (cmd == "git" and any(a.startswith("--config-env") for a in args)) or (cmd == "git" and any(
            args[i] == "-c" and re.match(r"(alias|remote|url|push|credential|core\.(sshcommand|hookspath))\.?",
                                         args[i + 1].lower()) for i in range(len(args) - 1))):
        return "git configuration overrides can redirect pushes and are not allowed"
    if cmd == "git":
        sub = git_subcommand(args)
        if sub[:1] == ["push"]:
            return push_reason(args, cwd)
        if sub[:1] == ["config"] and not GIT_CONFIG_READ & set(sub):
            return "git config changes repository or user configuration"
        if sub[:1] == ["remote"] and sub[1:2] and sub[1] in ("add", "set-url", "remove", "rename"):
            return "git remote changes repository configuration"
    if cmd == "gh":
        if args[:2] == ["pr", "create"]:
            return None if {"--draft", "-d"} & set(args) else \
                "gh pr create must open a draft (--draft); marking it ready stays with the user"
        if args[:1] == ["api"]:
            method = re.search(r"(?:^|\s)(?:-X|--method)[\s=]*(\w+)", " ".join(args))
            fields = any(re.match(r"-[fF]|--(raw-)?field|--input", a) for a in args)  # these default to POST
            if (method.group(1).upper() if method else "POST" if fields else "GET") != "GET":
                return "gh api request changes GitHub state"
        elif args[1:2] and args[0] not in ("search", "help") and args[1] not in GH_READ:
            return f"gh {' '.join(args[:2])} publishes or changes GitHub state"
    if "deploy" in cmd or (cmd in ("npm", "yarn", "pnpm", "bun", "make") and any("deploy" in a for a in args)):
        return "deploy commands are release actions"
    if cmd in DEPLOY_VERBS:
        verbs = DEPLOY_VERBS[cmd]
        if verbs is None or (args and args[0] in verbs):
            return f"{cmd} {' '.join(args[:1])} changes deployed infrastructure"
    if cmd in REMOTE or (cmd == "rsync" and any(re.match(r"^[^/\s]*[^/\s:]:", a) for a in args)):
        hosts, allowed = remote_hosts(cmd, args), (grant or {}).get("hosts", [])
        if hosts and all(h in allowed or h.split("@")[-1] in allowed for h in hosts):
            return None
        return f"{cmd} opens a remote shell or copy"
    if cmd in DATABASES:
        return f"{cmd} connects to a database; use a read-only data tool instead"
    if cmd == "aws":
        return aws_reason(args)
    if cmd in ("claude", "codex") and args[:1] not in (["--version"], ["agents"]):
        return f"{cmd} launches an agent outside delegate.py; use delegate.py start"
    if cmd in ("crontab", "launchctl") or (cmd == "defaults" and args[:1] == ["write"]):
        return f"{cmd} changes scheduled or system configuration"
    return write_reason(segment, cmd, args, cwd)


def write_reason(segment, cmd, args, cwd):
    writer = cmd in WRITERS or (cmd in ("sed", "perl") and any(a.startswith("-i") for a in args))
    targets = [a for a in args if not a.startswith("-")] if writer else []
    # Redirect targets; fd duplications (2>&1) do not match and /dev/null is not a write.
    targets += [t.strip("'\"") for t in re.findall(r">>?\|?\s*([^\s;|&<>]+)", segment) if t != "/dev/null"]
    if any(protected(t, cwd) for t in targets):
        return "writes to skills, settings, hooks or git configuration are not allowed"
    return None


def check_text(code):
    """Interpreter code: a command or secrets path in it is only text, so any mention blocks."""
    if re.search(r"--dangerously-skip-permissions\b", code):
        return "bypass flags are not allowed inside a worker"
    if "--approved" in code:
        return "only the attended session starts a release worker"
    if re.search(r"\bgit(\s+(-C\s+\S+|-c\s+\S+|--\S+))*\s+push\b", code) or \
            re.search(r"""["']git["'](\s*,\s*["'][^"']*["'])*?\s*,\s*["']push["']""", code):
        return "git push publishes commits"
    if SECRET.search(code) or KEY_DIRS.search(code):
        return "reading secrets files is not allowed"
    return None


def check_bash(command, cwd, depth=0):
    if depth > 3:
        return "nested shell wrappers are too deep to inspect"
    found, heredocs, _ = scan(command)
    for segment in found:
        reason = check_segment(segment, cwd, depth)
        if reason:
            return reason
        tokens = command_words(words(segment))
        if tokens[:1] in (["cd"], ["pushd"]) and tokens[1:2]:
            # A later write in the same command lands relative to the new directory.
            cwd = str(Path(cwd) / os.path.expanduser(tokens[1]))
    for body, feeders in heredocs:  # a heredoc body is data unless it feeds a shell or an interpreter
        heads = {os.path.basename(t[0]) for t in (command_words(words(s)) for s in feeders) if t}
        reason = check_bash(body, cwd, depth + 1) if heads & SHELLS else (
            check_text(body) if heads & INTERPRETERS else None)
        if reason:
            return reason
    return None


def check(event):
    tool, data = event["tool_name"], event.get("tool_input") or {}
    cwd = event.get("cwd") or os.getcwd()
    if tool == "Bash" or isinstance(data.get("command"), str):  # Bash, Monitor and any shell-running tool
        return check_bash(data["command"], cwd)
    if tool in ("Write", "Edit", "MultiEdit", "NotebookEdit"):
        path = data.get("file_path") or data.get("notebook_path")
        if protected(path, cwd):
            return f"editing {path} is not allowed"
    target = " " + str(data.get("file_path", ""))
    if tool == "Read" and (SECRET.search(target) or KEY_DIRS.search(target)):
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
