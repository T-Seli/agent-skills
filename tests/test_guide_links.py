import os
import re
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FILES = ["ENGINEERING-COORDINATOR.md"] + sorted(
    str(p.relative_to(ROOT)) for p in (ROOT / "skills/agent-coordination/references").glob("coordinator-*.md"))
LINK = re.compile(r"\]\(([^)#\s]+\.md)(?:#[^)]*)?\)")


class GuideLinks(unittest.TestCase):
    def broken(self, base, entry=lambda f: f):
        out = []
        for f in FILES:
            for m in LINK.finditer((ROOT / f).read_text()):
                if not os.path.exists(os.path.normpath(os.path.join(os.path.dirname(base / entry(f)), m.group(1)))):
                    out.append(f"{f}: {m.group(1)}")
        return out

    def test_links_resolve_from_checkout(self):
        self.assertEqual(self.broken(ROOT), [])

    def test_links_resolve_from_installed_layouts(self):
        for name in (".claude", ".agents"):
            home = Path(tempfile.mkdtemp()) / name
            (home / "skills").mkdir(parents=True)
            for d in (ROOT / "skills").iterdir():
                if d.is_dir():
                    os.symlink(d, home / "skills" / d.name)
            os.symlink(ROOT / "ENGINEERING-COORDINATOR.md", home / "ENGINEERING-COORDINATOR.md")
            out = []
            for f in FILES:  # lexical resolution, as an agent reading the installed path would do
                for m in LINK.finditer((ROOT / f).read_text()):
                    if not os.path.exists(os.path.normpath(os.path.join((home / f).parent, m.group(1)))):
                        out.append(f"{name} {f}: {m.group(1)}")
            self.assertEqual(out, [])


if __name__ == "__main__":
    unittest.main()
