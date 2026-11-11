import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import tomllib
import unittest
from agent_skills.codex_role_migration import OWNED,plan,apply_to_copy

ROOT=Path(__file__).resolve().parents[1]


class Roles(unittest.TestCase):
    def fixture(self):
        paths={n:f'/snapshot/codex/agents/{n}.toml' for n in OWNED}
        text='model = "keep-model"\n# keep user annotation\n[features]\nplugins = false\n'
        text+=''.join(f'\n[agents.{n}]\n# keep comment {n}\ndescription = "owned"\nconfig_file = {json.dumps(paths[n])}\n' for n in OWNED)
        text+='\n[agents.custom]\ndescription = "user role"\nconfig_file = "/keep/custom.toml"\n'
        return text,{n:{'description':'owned','config_file':paths[n]} for n in OWNED}

    def test_conditional_removal_preserves_unrelated_fields_comments_and_refuses_newer_edits(self):
        text,paths=self.fixture();migration=plan(text,paths);staged=apply_to_copy(text,migration,paths)
        parsed=tomllib.loads(staged)
        self.assertEqual(parsed['model'],'keep-model');self.assertFalse(parsed['features']['plugins'])
        self.assertEqual(list(parsed['agents']),['custom'])
        for n in OWNED:self.assertIn('# keep comment '+n,staged)
        with self.assertRaisesRegex(ValueError,'changed after review'):apply_to_copy(text+'\n# newer edit\n',migration,paths)
        with self.assertRaises(ValueError):plan(text.replace('/snapshot/','/user-custom/'),paths)
        with self.assertRaisesRegex(ValueError,'differs; preserve user changes'):
            plan(text.replace('description = \"owned\"','description = \"custom user routing\"',1),paths)

    def test_installer_copies_regular_roles_and_collision_holds_before_changes(self):
        with tempfile.TemporaryDirectory() as temp:
            dest=Path(temp).resolve()/'isolated';dest.mkdir()
            run=subprocess.run([str(ROOT/'install.sh'),'--target=codex',f'--destination-root={dest}'],capture_output=True,text=True)
            self.assertEqual(run.returncode,0,run.stderr)
            role=dest/'.codex/agents/local-scout.toml'
            self.assertTrue(role.is_file());self.assertFalse(role.is_symlink())
            self.assertEqual(role.read_bytes(),(ROOT/'codex/agents/local-scout.toml').read_bytes())
            sentinel=dest/'.codex/config.toml';sentinel.write_text('[agents.local-scout]\ndescription="custom"\nconfig_file="/preserve"\n')
            before=role.read_bytes();config=sentinel.read_bytes()
            blocked=subprocess.run([str(ROOT/'install.sh'),'--target=all',f'--destination-root={dest}'],capture_output=True,text=True)
            self.assertNotEqual(blocked.returncode,0);self.assertIn('collide',blocked.stderr)
            self.assertEqual(role.read_bytes(),before);self.assertEqual(sentinel.read_bytes(),config)
            self.assertFalse((dest/'.claude/skills').exists())


if __name__=='__main__':unittest.main()
