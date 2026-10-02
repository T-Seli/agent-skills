"""Navigation for hub summaries: how the user gets from a summary to the thread or the session.

A link is clickable only when it was parsed out of an adapter or API response (with a receipt of
that response) and its host is on the allowlist the caller passes when rendering. A label saying a
link was verified proves nothing, so it is never enough. App schemes (codex://, claude://) and local
files don't open from the chat thread. Without a trusted link, the summary names the app and
session, and the details reply carries the id and a resume command verified for this machine.
"""
import hashlib
import json
import re
import shlex
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlsplit

# One plain shape, read the same way by every parser and browser: lowercase host, no userinfo, port,
# backslash or trailing dot; the path holds no space, backslash or chat markup characters.
HTTPS = re.compile(r"https://(?P<host>[a-z0-9-]+(?:\.[a-z0-9-]+)+)(?P<path>/[^\s<>|\\]*)?")
# Responses a link may be parsed from: the code host's CLI or API (e.g. a JSON url field), the
# messaging connector's send result, or the worker platform's own session output.
SOURCES = {"code-host", "connector", "platform"}
APPS = {"claude": "Claude Code", "codex": "Codex"}
# Resume commands whose CLI support is verified (`--help` and official docs); valid only when the
# session's transcript is on this machine.
RESUME = {"claude": ("claude", "--resume"), "codex": ("codex", "resume")}


def _host(url):
    m = HTTPS.fullmatch(url) if isinstance(url, str) else None
    return m.group("host") if m and urlsplit(url).hostname == m.group("host") else None


def _field(raw, field):
    value = json.loads(raw)
    for part in field.split("."):
        if not isinstance(value, dict) or part not in value:
            raise ValueError(f"the response has no field {field!r}")
        value = value[part]
    return value


def link_from_response(raw, field, *, source, allowed_hosts):
    """Parse a URL out of a JSON response (`field` is a dotted path) and keep a receipt; ValueError
    unless it is https on an allowed host. Never a guessed URL, an app scheme or a local file."""
    if source not in SOURCES:
        raise ValueError(f"unknown response source {source!r}")
    value = _field(raw, field)
    host = _host(value)
    if not host or host not in allowed_hosts:
        raise ValueError("the response did not give an https link on an allowed host")
    # The response itself isn't kept (a send result can carry a message body); its hash is, plus a
    # hash binding the field to this URL, so a URL changed after parsing no longer matches.
    return {"url": value, "host": host, "receipt": {"source": source, "field": field,
                                                    "sha256": hashlib.sha256(raw.encode()).hexdigest(),
                                                    "binding": _binding(field, value)}}


def _binding(field, url):
    return hashlib.sha256(f"{field}\n{url}".encode()).hexdigest()


def trusted(lnk, allowed_hosts):
    """The URL to render, or None: the receipt's binding re-checked against this URL, and the host
    against the caller's allowlist. The receipt is evidence of where the URL came from, not proof:
    whether the response was genuine rests on the code that called the adapter or API."""
    if not isinstance(lnk, dict) or not isinstance(lnk.get("receipt"), dict):
        return None
    rc, url = lnk["receipt"], lnk.get("url")
    host = _host(url)
    ok = (host and host == lnk.get("host") and host in allowed_hosts and rc.get("source") in SOURCES
          and isinstance(rc.get("field"), str) and re.fullmatch(r"[0-9a-f]{64}", str(rc.get("sha256") or ""))
          and rc.get("binding") == _binding(rc["field"], url))
    return url if ok else None


def session(kind, session_id, name, *, on_this_machine, url=None):
    """A session reference. `url` is a link_from_response() result or None; `on_this_machine` means its transcript
    was found locally, so the resume command works here."""
    if kind not in APPS:
        raise ValueError(f"unknown worker kind {kind!r}")
    resume = None
    if on_this_machine:
        resume = " ".join(shlex.quote(p) for p in (*RESUME[kind], session_id))
    return {"app": APPS[kind], "id": session_id, "name": name, "url": url, "resume": resume}


def checked(ref, clean, allowed_hosts=()):
    """Re-validate a session reference built elsewhere: known app, safe id, resume command matching
    the id, and the name passed through `clean`, so no field can add a line or a link. A url that
    isn't trusted() is dropped, so the line falls back to the app and session name."""
    kinds = {app: kind for kind, app in APPS.items()}
    if ref.get("app") not in kinds or not re.fullmatch(r"[\w.-]+", str(ref.get("id") or "")):
        raise ValueError("session reference must come from nav.session()")
    url = trusted(ref.get("url"), allowed_hosts)
    expected = session(kinds[ref["app"]], ref["id"], "", on_this_machine=True)["resume"]
    if ref.get("resume") not in (None, expected):
        raise ValueError("resume command does not match the session id")
    return dict(ref, name=clean(ref.get("name")), url=url)


def session_line(ref):
    """The coding-session destination: a trusted link, or the app and session name with an honest way to open it."""
    if ref is None:
        return "Open coding session: not recorded"
    if ref["url"]:
        return f"Open coding session: <{ref['url']}|Open in {ref['app']}>"
    if ref["resume"]:
        return f"Open coding session: {ref['app']} · “{ref['name']}” · on this Mac (resume command in details)"
    return f"Open coding session: {ref['app']} · “{ref['name']}” · not on this Mac; open it from {ref['app']} where it runs"


ROOT_TS = re.compile(r"\d{10}\.\d{6}")
CHANNEL = re.compile(r"[A-Z0-9]{2,20}")
CHAT = re.compile(r"[A-Za-z][A-Za-z ]{0,19}")


def thread(root_ts, *, channel, inside, permalink=None, chat="chat"):
    """The work item's thread: the recorded channel (destination id) and exact root ts as strings,
    whether this summary is posted inside it, and a permalink only as a link_from_response() result
    from the connector's own response. `chat` names the messaging app (from the private config)."""
    if not (isinstance(chat, str) and CHAT.fullmatch(chat)):
        raise ValueError("chat must be a short plain app name")
    if not (isinstance(channel, str) and CHANNEL.fullmatch(channel)):
        raise ValueError(f"channel {channel!r} must be the recorded destination id")
    if root_ts is not None and not (isinstance(root_ts, str) and ROOT_TS.fullmatch(root_ts)):
        raise ValueError(f"root ts {root_ts!r} must be the recorded timestamp string (floats lose digits)")
    if not isinstance(inside, bool):
        raise ValueError("inside must be True or False")
    return {"root_ts": root_ts, "channel": channel, "inside": inside, "permalink": permalink, "chat": chat}


def _names_root(url, channel, root_ts):
    """A permalink is /archives/<channel>/p<ts digits>; a reply's permalink adds thread_ts and cid. It
    must name this channel and this root, so the same ts in another channel fails. This checks a
    returned link; it never builds one."""
    parts = urlsplit(url)
    q = parse_qs(parts.query)
    segs = parts.path.rstrip("/").split("/")
    if len(segs) != 4 or segs[:3] != ["", "archives", channel] or not re.fullmatch(r"p\d{16}", segs[3]):
        return False
    if "cid" in q and q["cid"] != [channel]:
        return False
    if "thread_ts" in q:
        return q["thread_ts"] == [root_ts]
    return segs[-1] == "p" + root_ts.replace(".", "")


def thread_line(ref, allowed_hosts=(), *, in_index=False):
    """The thread destination, rebuilt from `ref` through thread() so a forged entry fails: a trusted
    connector permalink naming this channel and root, else reply-here when the summary sits in that
    thread, else an honest fallback. A code-host or other link never stands in. In the index (no
    details reply there) the fallback names the app and when the thread started, so it can be found."""
    if ref is None:
        return "Open chat thread: no thread yet"
    if not isinstance(ref, dict) or set(ref) != {"root_ts", "channel", "inside", "permalink", "chat"}:
        raise ValueError("thread reference must come from nav.thread()")
    ref = thread(ref["root_ts"], channel=ref["channel"], inside=ref["inside"], permalink=ref["permalink"], chat=ref["chat"])
    label = f"Open {ref['chat']} thread"
    if not ref["root_ts"]:
        return f"{label}: no thread yet"
    link = ref["permalink"]
    url = trusted(link, allowed_hosts)
    if url and link["receipt"]["source"] == "connector" and _names_root(url, ref["channel"], ref["root_ts"]):
        return f"{label}: <{url}|{label}>"
    if in_index:
        started = datetime.fromtimestamp(int(ref["root_ts"].split(".")[0]), timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        return f"{label}: in {ref['chat']}, the thread started {started} (no link here)"
    if ref["inside"]:
        return f"{label}: reply in this thread"
    return f"{label}: no verified link (root recorded in details)"


def session_details(ref):
    parts = [f"{ref['app']} session {ref['id']}"]
    if ref["resume"]:
        parts.append(f"resume: `{ref['resume']}`")
    return " · ".join(parts)
