#!/usr/bin/env python3
"""Build a self-contained before/after approval page. Usage: build_pairs.py spec.json out.html
spec: {"title","intro","items":[{"n","name","what","before","after"}]}  (before/after = png paths)"""
import base64, html, json, sys

spec = json.load(open(sys.argv[1]))
def uri(p):
    return "data:image/png;base64," + base64.b64encode(open(p, "rb").read()).decode()

css = """
<title>%s</title>
<meta name="claude:viewport-fit-sides" content="cover">
<style>
:root{--bg:#f6f7f9;--fg:#14181f;--mute:#566070;--card:#fff;--line:#d6dbe3;--accent:#1f5fbf;--bad:#a4332b;--good:#1d7a46}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#0f1319;--fg:#e8ecf2;--mute:#9aa6b8;--card:#171d27;--line:#2a3342;--accent:#6aa3ff;--bad:#ff8b80;--good:#5fd38d;color-scheme:dark}}
:root[data-theme="dark"]{--bg:#0f1319;--fg:#e8ecf2;--mute:#9aa6b8;--card:#171d27;--line:#2a3342;--accent:#6aa3ff;--bad:#ff8b80;--good:#5fd38d;color-scheme:dark}
body{background:var(--bg);color:var(--fg);font:15px/1.5 Inter,system-ui,sans-serif;padding-block:24px;padding-left:max(16px,env(safe-area-inset-left,0px));padding-right:max(16px,env(safe-area-inset-right,0px))}
main{max-width:980px;margin:0 auto;display:flex;flex-direction:column;gap:20px}
h1{font-size:24px;margin:0;text-wrap:balance}p{margin:0;color:var(--mute)}
section{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:16px;display:flex;flex-direction:column;gap:12px;min-width:0}
h2{font-size:18px;margin:0}
.pair{display:grid;grid-template-columns:1fr 1fr;gap:12px}
@media(max-width:700px){.pair{grid-template-columns:1fr}}
figure{margin:0;display:flex;flex-direction:column;gap:6px;min-width:0}
figcaption{font-size:12px;letter-spacing:.08em;text-transform:uppercase;font-weight:600}
.b figcaption{color:var(--bad)}.a figcaption{color:var(--good)}
img{max-width:100%%;border:1px solid var(--line);border-radius:6px;background:#fff}
</style>
""" % html.escape(spec["title"])

out = [css, "<main>", "<h1>%s</h1>" % html.escape(spec["title"]), "<p>%s</p>" % html.escape(spec["intro"])]
for it in spec["items"]:
    out.append(
        "<section><h2>%s. %s</h2><p>%s</p><div class=pair>"
        "<figure class=b><figcaption>Before</figcaption><img alt='Before' src='%s'></figure>"
        "<figure class=a><figcaption>After</figcaption><img alt='After' src='%s'></figure>"
        "</div></section>" % (it["n"], html.escape(it["name"]), html.escape(it["what"]), uri(it["before"]), uri(it["after"]))
    )
out.append("</main>")
open(sys.argv[2], "w").write("\n".join(out))
print("ok", sys.argv[2])
