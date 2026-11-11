"""Shared skill text: handoff route/session lines, question cadence default and consent scope."""
import re
import json
import os
import subprocess
import tempfile
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
def text(path): return (ROOT / path).read_text(encoding='utf-8')
CONTRACTS = 'skills/workflow-contracts/contracts.md'


class HandoffTemplate(unittest.TestCase):
    def template(self):
        return re.search(r'## Template\n```\n(.*?)```', text('skills/handoff/SKILL.md'), re.S).group(1)

    def test_route_access_and_session_lines_are_in_the_template(self):
        lines = self.template().splitlines()
        route = next(x for x in lines if x.startswith('Route & access:'))
        for field in ('owned by', 'requested', 'ceiling', 'observed <model | unknown>/<effort | unknown>',
                      'auth context', 'readiness', 'missing:', 'limits:'):
            self.assertIn(field, route)
        session = next(x for x in lines if x.startswith('Session:'))
        self.assertIn('fresh', session)
        self.assertIn('authorized resume', session)
        self.assertIn('do not resume, continue or take it over', session)

    def test_filled_non_git_handoff_fits_the_cap_with_unknown_effort(self):
        filled = []
        for line in self.template().splitlines():
            if line.startswith('Recent commits'):
                continue  # dropped outside a git repo
            if line.startswith('Route & access:'):
                line = ('Route & access: source s-1 owned by worker-a · requested claude-opus-5-5/medium (ceiling high)'
                        ' · observed claude-opus-5-5/unknown · environment normal-mac, auth context mac-user,'
                        ' readiness readiness:normal-mac 10m · missing: db:fixture · limits: effort not exposed')
            filled.append(re.sub(r'<[^>]*>', 'fixture value', line))
        block = '\n'.join(filled)
        self.assertIn('/unknown', block)
        self.assertLessEqual(len(filled), 40)
        self.assertLessEqual(len(block.split()), 450)


class DataAccessReadiness(unittest.TestCase):
    def test_scout_readiness_gate_applies_only_to_declared_capabilities(self):
        habits = text('skills/workflow-contracts/data-access.md').split('## Habits', 1)[1]
        line = next(x for x in habits.splitlines() if 'readiness' in x)
        self.assertNotIn('Brief a scout only after', line)  # unconditional gate on every scout
        self.assertIn('declares', line)
        for kept in ('missing, stale or mismatched', 'never grants', 'Never probe or create access'):
            self.assertIn(kept, line)


class QuestionsAndConsent(unittest.TestCase):
    def test_round_size_is_a_proposed_configurable_default(self):
        defaults = text(CONTRACTS).split('## Defaults', 1)[1]
        line = next(x for x in defaults.splitlines() if x.startswith('- Question round size:'))
        self.assertIn('1–3', line)
        self.assertIn('proposed', line)
        for path in ('skills/workflow-contracts/decisions.md', 'skills/grill-me/SKILL.md'):
            body = text(path)
            self.assertIn('`Question round size`', body)
            self.assertNotIn('normally one to three', body)

    def test_bare_approval_and_named_steps_do_not_conflict(self):
        body = text(CONTRACTS)
        self.assertNotIn('applies only to its concrete pending action', body)
        self.assertNotIn('to the end of the chain', body)
        consent = body.split('## Consent', 1)[1].split('##', 1)[0]
        self.assertIn('covers the concrete pending gated step', consent)
        self.assertIn('covers every step it names', consent)
        self.assertIn("don't ask again or per step", consent)


class DepthNotBreadth(unittest.TestCase):
    def test_global_rule_and_shared_contract_reach_the_execution_detail(self):
        global_rule = text('global/CLAUDE.md')
        self.assertIn('Depth, not breadth', global_rule)
        self.assertIn('workflow-contracts/behavior.md', global_rule)
        self.assertIn('then [behavior.md](behavior.md)', text(CONTRACTS))
        self.assertLessEqual(len(global_rule.split()), 600)
        self.assertLessEqual(len(text(CONTRACTS).splitlines()), 90)

    def test_original_rewrite_request_is_preserved_with_its_scope_boundary(self):
        body = text('skills/workflow-contracts/behavior.md')
        original = "I want a deeper version of this task, not a bigger one. Before rewriting it: (1) say what a top professional in this field would do here that I’m not asking for; (2) name the rawest material they would start from instead of what has already been digested for me; (3) name the specific methods and tools they would use; (4) say what, other than you or me, would show the result is right. Then rewrite my prompt to ask for exactly that."
        self.assertIn(original, body)
        for boundary in ('Rewrite a prompt only when asked', 'primary evidence',
                         'independent observable check', 'never probe denied access',
                         'Preserve privacy, exclusions, settled decisions and all permission gates'):
            self.assertIn(boundary, body)

    def test_every_catalog_consumer_actually_loads_the_shared_rule(self):
        catalog = json.loads(text('agent_skills/catalog.json'))
        for skill in catalog['skills']:
            for role in skill['roles']:
                with self.subTest(skill=skill['id'], role=role):
                    run = subprocess.run(
                        ['python3', '-m', 'agent_skills', 'load', '--role', role, skill['id']],
                        cwd=ROOT, capture_output=True, text=True)
                    self.assertEqual(run.returncode, 0, run.stderr)
                    sources = json.loads(run.stdout)['sources']
                    detail = [s for s in sources if s['path'] == 'skills/workflow-contracts/behavior.md']
                    self.assertEqual(len(detail), 1)
                    self.assertIn('## Depth, not breadth', detail[0]['content'])

    def test_isolated_installer_delivers_rule_and_detail_to_both_adapters(self):
        with tempfile.TemporaryDirectory() as home:
            run = subprocess.run([str(ROOT / 'install.sh')], cwd=ROOT,
                                 env=dict(os.environ, HOME=home), capture_output=True, text=True)
            self.assertEqual(run.returncode, 0, run.stderr)
            for global_path, skills_path in (
                ('.claude/CLAUDE.md', '.claude/skills'),
                ('.codex/AGENTS.md', '.agents/skills'),
            ):
                with self.subTest(adapter=global_path):
                    self.assertIn('Depth, not breadth', (Path(home) / global_path).read_text())
                    self.assertIn('workflow-contracts/behavior.md', (Path(home) / global_path).read_text())
                    contracts = Path(home) / skills_path / 'workflow-contracts'
                    self.assertIn('then [behavior.md](behavior.md)', (contracts / 'contracts.md').read_text())
                    self.assertEqual((contracts / 'behavior.md').read_text(),
                                     text('skills/workflow-contracts/behavior.md'))
                    # Delivery in an isolated HOME is adapter proof, not native selection.
                    ui = Path(home) / skills_path / 'ui-design' / 'SKILL.md'
                    self.assertEqual(ui.read_text(), text('skills/ui-design/SKILL.md'))
                    delivered = (contracts / 'contracts.md').read_text().split('## Chain', 1)[1].split('## Consent', 1)[0]
                    self.assertIn('**ui-design**', delivered)
                    self.assertIn('preserve phase authority, design choice and consent', delivered)
            self.assertIn('$ui-design', (Path(home) / '.codex/AGENTS.md').read_text())


class CriticalExecutionNavigation(unittest.TestCase):
    def test_entrypoint_reaches_existing_concrete_foreground_contract(self):
        body=text('skills/agent-coordination/SKILL.md')
        self.assertIn('references/state.md § Bounded recovery assessment',body)
        contract=text('skills/agent-coordination/references/state.md')
        for command in ('keep-awake status', 'keep-awake acquire', 'keep-awake reuse', 'keep-awake renew|release'):
            self.assertIn(command,contract)
        self.assertIn('queues control, not completion',contract)


class PrimaryCoordinatorGuide(unittest.TestCase):
    """Static guide/decision-table checks, never runtime enforcement."""
    def cases(self):
        body=text('ENGINEERING-COORDINATOR.md')
        self.assertIn('### Primary-role validation cases',body)
        section=body.split('### Primary-role validation cases',1)[1].split('## 2.',1)[0]
        rows=[line.split('|')[1:-1] for line in section.splitlines() if line.startswith('| ')]
        return {row[0].strip():row[1].strip() for row in rows if len(row)==3 and row[0].strip() not in ('Case','---')}

    def test_primary_execution_is_delegated_not_permitted_by_generic_orchestrator_label(self):
        cases=self.cases()
        for case in ('Edit files or mutate Git or GitHub','Run tests, release or operate production',
                     'Spec-mode record/worktree/tick/publish/fast-forward/cleanup mutation'):
            with self.subTest(case=case):self.assertEqual(cases[case],'DELEGATE')
        body=text('ENGINEERING-COORDINATOR.md')
        self.assertIn('Primary-role precedence',body)
        self.assertIn('generic “orchestrator” label',body)
        self.assertIn('no-code/no-diff',body)

    def test_orphaned_completion_is_held_but_real_terminal_closure_and_waits_are_allowed(self):
        cases=self.cases()
        expected={'Read-only investigation or evidence inspection':'READ',
            'Completed result; unresolved obligations; next owner/action missing':'HOLD',
            'Completed result; authorized follow-up assigned with owner/checkpoint':'RECONCILE',
            'Whole outcome verified complete; all obligations dispositioned':'CLOSE',
            'Deliberate approval/access/dependency wait with owner/checkpoint':'RETAIN',
            'Unknown inventory or overdue/idle lane without current result':'INSPECT'}
        for case,decision in expected.items():
            with self.subTest(case=case):self.assertEqual(cases[case],decision)
        self.assertIn('not live runtime enforcement',text('ENGINEERING-COORDINATOR.md'))

    def test_start_resume_checks_readability_without_claiming_commit_prevents_eviction(self):
        body=text('ENGINEERING-COORDINATOR.md')
        for fact in ('Source-availability preflight','committed locally','pushed remotely','installed',
                     'does not prevent file eviction','never reset/overwrite','stale main',
                     'lost/unverifiable read-only receipts'):
            with self.subTest(fact=fact):self.assertIn(fact,body)

    def test_reviewer_checks_primary_inventory_through_existing_shared_queue(self):
        body=text('ENGINEERING-COORDINATOR.md')
        self.assertIn('### Independent reviewer checkpoint',body)
        section=body.split('### Independent reviewer checkpoint',1)[1].split('## 6.',1)[0]
        for fact in ('actual live inventory','durable checkpoints','canonical shared queue',
                     'stable IDs','source/revision','observation time','aging decisions',
                     'approvals','grill-me questions','intentional waits',
                     'does not silently take over','does not grant permission','always-on',
                     'user-owned primary coordinator sessions','assistant-created workers',
                     'uncovered or unobserved lanes','private findings','same exact revision',
                     'both source receipts','responsible owner','must not erase unresolved evidence',
                     'skills/workflow-contracts/decisions.md',
                     'skills/workflow-contracts/references/review-evidence.md'):
            with self.subTest(fact=fact):self.assertIn(fact,section)

    def test_small_release_checks_bind_reuse_and_preserve_required_gates(self):
        body=text('ENGINEERING-COORDINATOR.md').split('## 6. Preserve traceability and review the same artifact',1)[1].split('## 7.',1)[0]
        paragraphs=[line for line in body.splitlines() if line.startswith('Keep small releases proportionate to risk.')]
        self.assertEqual(len(paragraphs),1)
        paragraph=paragraphs[0]
        for binding in ('exact artifact/base','relevant paths','dependencies','configuration',
                        'toolchain','environment','acceptance criteria','command'):
            with self.subTest(binding=binding):self.assertIn(binding,paragraph)
        for rule in ('Record why each check is reused or rerun','invalidate affected evidence',
                     'focused, impact-driven checks','canonical aggregate checks','independent review',
                     'safety, approval, target-readiness, release, and rollback gates',
                     'never silently skip it','Reused, skipped, blocked, and not-run checks are never newly passed',
                     'remaining checks and their owner','no automatic release or deployment authority'):
            with self.subTest(rule=rule):self.assertIn(rule,paragraph)

    def test_no_direct_execution_grant_and_templates_name_next_owner(self):
        body=text('ENGINEERING-COORDINATOR.md')
        mode=text('skills/agent-coordination/references/coordinator-mode.md')
        for grant in ('The primary coordinator may edit files','The primary coordinator may run tests',
                      'A finished worker automatically closes the whole task'):
            for doc in (body,mode):
                with self.subTest(grant=grant):self.assertNotIn(grant,doc)
        start=body.split('Use this startup brief',1)[1].split('```',2)[1]
        self.assertIn('Next checkpoint/stopping condition',start)
        self.assertIn('Worker stop packet',body)
        stop=body.split('Worker stop packet',1)[1].split('```text',1)[1].split('```',1)[0].strip()
        self.assertEqual(len(stop.splitlines()),6)
        for binding in ('task <task-id>','deliverable <id>','revision <n>','digest <digest>','next-action <bound action>'):
            with self.subTest(binding=binding):self.assertIn(binding,stop.splitlines()[0])
        for field in ('STOP <task-key>','Result:','Artifact:','Open:','Need:','Next: <owner> by <time>'):
            with self.subTest(field=field):self.assertIn(field,stop)

    def test_board_ledger_and_native_question_rules_are_present(self):
        body=text('ENGINEERING-COORDINATOR.md')
        self.assertIn('### Board, ledger and owed list',body)
        board=body.split('### Board, ledger and owed list',1)[1].split('## 3.',1)[0]
        for fact in ('Need from you: N','NEED FROM YOU','READY TO ACT','RUNNING','HELD','DONE SINCE LAST',
                     'CLEANUP BATCH','TASKS.md','same turn','48 hours','Owed list'):
            with self.subTest(fact=fact):self.assertIn(fact,board)
        for fact in ('(Recommended)','executing worker in its own session','authenticated original approval','action-time permission flow',
                     'one release card','Refs <owner/repo>#<n>'):
            with self.subTest(fact=fact):self.assertIn(fact,body)

    def test_coordination_formats_preserve_authority_capability_and_queue_ownership(self):
        body=text('ENGINEERING-COORDINATOR.md');mode=text('skills/agent-coordination/references/coordinator-mode.md')
        decisions=text('skills/workflow-contracts/decisions.md')
        for fact in ('canonical project queue','verified record owner','not a second project queue',
                     '48 hours','age alone never closes','materially changed scope/revision',
                     'details readability','consumer readback','supported authorized route',
                     'live and unknown runs','including scouts and reviewers',
                     'proven not admitted','uncertain delivery effects','required split handoffs',
                     'implementation-scoped','no new standing grant'):
            with self.subTest(fact=fact):self.assertIn(fact,body)
        self.assertIn('verified record owner',mode);self.assertIn('canonical project queue',mode)
        for fact in ('technical preparation','consolidates','action-time permission flow',
                     'authenticated original approval','generic question UI'):
            with self.subTest(fact=fact):self.assertIn(fact,decisions)
        for unsafe in ('scouts and read-only reviewers do not count','an unacknowledged send is resent once',
                       'relaunch once through the same route','PRs use `Refs #n`'):
            with self.subTest(unsafe=unsafe):self.assertNotIn(unsafe,body)

    def test_contradiction_examples_cannot_pass_the_static_grant_check(self):
        def check(doc):
            for grant in ('The primary coordinator may edit files','The primary coordinator may run tests',
                          'A finished worker automatically closes the whole task'):
                self.assertNotIn(grant,doc)
        check(text('ENGINEERING-COORDINATOR.md'))
        for grant in ('The primary coordinator may edit files','The primary coordinator may run tests',
                      'A finished worker automatically closes the whole task'):
            with self.subTest(grant=grant),self.assertRaises(AssertionError):
                check(text('ENGINEERING-COORDINATOR.md')+'\n'+grant)

    def test_release_card_exposes_exact_candidate_and_real_gates(self):
        body=text('ENGINEERING-COORDINATOR.md')
        self.assertIn('Release card template',body)
        card=body.split('Release card template',1)[1].split('```text',1)[1].split('```',1)[0]
        for field in ('Release/target/owner:','Candidate/source:','Includes/gates:',
                      'Evidence:','Readiness/approval:','Plan/command:',
                      'Rollback/observability:','Disposition:'):
            with self.subTest(field=field):self.assertIn(field,card)
        self.assertIn('required split handoffs',body)
        self.assertIn('implementation-scoped',body)

class RoleLoopGuidance(unittest.TestCase):
    def test_role_map_is_discoverable_and_composed(self):
        from agent_skills import Catalog
        role_path='skills/agent-coordination/references/roles.md'
        self.assertTrue((ROOT/role_path).is_file())
        role=text(role_path)
        for phrase in ('Primary coordinator','Execution worker','Independent reviewer/researcher',
                       'Cross-task executive','Record owner','Release/monitor owner',
                       'startup, resume or compaction','material scope/revision/role change',
                       'relevant miss','exact source','matching readback'):
            with self.subTest(phrase=phrase):self.assertIn(phrase,role)
        self.assertIn('references/roles.md',text('skills/agent-coordination/SKILL.md'))
        loaded=Catalog(ROOT).load('company.agent-coordination',role='worker')
        paths=[s['path'] for s in loaded['sources']]
        self.assertIn(role_path,paths)
        self.assertNotIn('skills/agent-coordination/references/independent-reviewer.md',paths)
        self.assertIn('references/roles.md',text('README.md'))

    def test_independent_role_preserves_scope_and_finding_readback(self):
        path='skills/agent-coordination/references/independent-reviewer.md'
        self.assertTrue((ROOT/path).is_file())
        role=text(path)
        for phrase in ('read-only research','not implementation','current policy',
                       'recipient/category','no new schedule','bounded checkpoints',
                       'source/timestamp','primary acknowledges','verified resolution',
                       'positive review','same exact revision','permission',
                       'primary sources','unavailable coverage','used/skipped'):
            with self.subTest(phrase=phrase):self.assertIn(phrase,role)
        self.assertIn('independent-reviewer.md',text('skills/system-audit/references/reviewers.md'))
        self.assertIn('independent-reviewer.md',text('agents/skill-reviewer.md'))
        self.assertIn('independent-reviewer.md',text('codex/agents/skill-reviewer.toml'))

    def test_brief_and_stop_keep_budgets_and_applicability(self):
        body=text('ENGINEERING-COORDINATOR.md')
        brief=body.split('Use this assignment template',1)[1].split('```text',1)[1].split('```',1)[0].strip()
        self.assertLessEqual(len(brief.splitlines()),15)
        stop=body.split('Worker stop packet',1)[1].split('```text',1)[1].split('```',1)[0].strip()
        self.assertEqual(len(stop.splitlines()),6)
        self.assertIn('skills <used/skipped: reason>',stop)
        for phrase in ('Rules of the road','applicable governing phase','meaningful checkpoints',
                       'already authorized scoped corrections','independent-reviewer.md'):
            with self.subTest(phrase=phrase):self.assertIn(phrase,body)
        for unsafe in ('Report only by stop packet','Use the skills in order',
                       'Refs #n','dot does no work and starts nothing'):
            with self.subTest(unsafe=unsafe):self.assertNotIn(unsafe,body)

    def test_autonomous_review_remains_bounded_and_role_refs_are_delivered(self):
        role=text('skills/agent-coordination/references/independent-reviewer.md')
        for phrase in ('authorized autonomous read-only scope','routine check inventory',
                       'bounded wake/readback','actual transport receipts','not a scheduler'):
            with self.subTest(phrase=phrase):self.assertIn(phrase,role)
        # Delivery rehearsal only: no active installed roots or native inference.
        with tempfile.TemporaryDirectory() as tmp:
            result=subprocess.run([str(ROOT/'install.sh'), '--destination-root='+tmp],
                                  capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            for adapter in ('.claude/skills','.agents/skills'):
                for name in ('roles.md','independent-reviewer.md','reviewer-access.md'):
                    delivered=Path(tmp)/adapter/'agent-coordination/references'/name
                    self.assertEqual(delivered.read_bytes(),
                        (ROOT/'skills/agent-coordination/references'/name).read_bytes())

    def test_policy_request_route_never_self_authorizes(self):
        routing=text('skills/agent-coordination/references/routing.md')
        for phrase in ('read-only review or research request','current policy',
                       'recipient/category','exclusions','route rejects','not authority'):
            with self.subTest(phrase=phrase):self.assertIn(phrase,routing)
        skill=text('skills/agent-coordination/SKILL.md')
        self.assertIn('coordinator consolidates',skill)
        self.assertNotIn('technical grilling in the existing owning worker',skill)
        self.assertIn('explicitly chosen',skill)

class ReleaseAndAccessGuidance(unittest.TestCase):
    def test_deploy_reconciles_real_target_and_changed_scope(self):
        deploy=text('skills/deploy/SKILL.md')
        for phrase in ('target-specific live identity','not assume a target Git checkout',
                       'unknown mapping holds','actual changed scope','authorized monitor owner',
                       'observation/acceptance pending','deployment result separately'):
            with self.subTest(phrase=phrase):self.assertIn(phrase,deploy)
        self.assertNotIn('NOT SHIPPED: no monitor',deploy)

    def test_collision_reads_do_not_grant_external_claims(self):
        body=text('skills/implement/SKILL.md')
        for phrase in ('configured/available base','supported authorized issue/PR',
                       'gh is not universal','blank assignee is not claim authority',
                       'unknown inventory','existing helpers'):
            with self.subTest(phrase=phrase):self.assertIn(phrase,body)
        self.assertNotIn('none means claim it',body)

    def test_monitor_escalation_keeps_denial_and_resolution_boundaries(self):
        monitor=text('skills/monitor/SKILL.md')
        for phrase in ('changed identifiers/configuration','coverage gaps','named escalation route',
                       'actual supported transport','acknowledgment is not resolution',
                       'no automatic retry after denial','configured authorized janitor',
                       'uncertain outcomes require readback'):
            with self.subTest(phrase=phrase):self.assertIn(phrase,monitor)
        self.assertNotIn('the daily janitor retries',monitor)

    def test_separate_deploy_gate_does_not_expand_implementation_only_scope(self):
        issues=text('skills/workflow-contracts/issues.md')
        for phrase in ('accepted issue scope includes a separate deployment',
                       'Refs <owner/repo>#<n>','implementation-only scope',
                       'actual observation/human obligations'):
            with self.subTest(phrase=phrase):self.assertIn(phrase,issues)
        self.assertIn("only at the issue's stated acceptance gate",issues)
        self.assertIn('One outstanding release candidate per repo',text('skills/workflow-contracts/behavior.md'))
        self.assertIn('already given takes nothing new',text('skills/workflow-contracts/behavior.md'))

    def test_access_reference_distinguishes_capability_failures_without_provisioning(self):
        path='skills/agent-coordination/references/reviewer-access.md'
        self.assertTrue((ROOT/path).is_file())
        body=text(path)
        cases={
            'installed-not-usable':('installed connector','effective access'),
            'expired-not-denied':('MFA-expired','denied'),
            'cloud-not-session':('infrastructure telemetry','native agent/session state'),
            'read-side-effects':('read-named operations','queue consumption'),
            'renewal-restart':('renewal','restart recovery','degraded'),
            'no-false-live-pass':('empty result','freshness','unknown'),
            'provisioning-separate':('not provisioning authority','separate approval')}
        for case,phrases in cases.items():
            for phrase in phrases:
                with self.subTest(case=case,phrase=phrase):self.assertIn(phrase,body)
        self.assertIn('reviewer-access.md',text('skills/agent-coordination/references/independent-reviewer.md'))

class DocumentationCurrencyGuidance(unittest.TestCase):
    def test_canonical_documentation_contract_preserves_provenance_and_authority(self):
        body=text('skills/workflow-contracts/behavior.md')
        self.assertIn('## Documentation currency',body)
        docs=body.split('## Documentation currency',1)[1].split('\n## ',1)[0]
        for phrase in ('canonical links','verified changes','source/revision',
                       'proposed, answered, deferred or superseded','meeting summaries',
                       'not themselves user approval','conflicting sources','uncertainty',
                       'recoverability','no silent deletion','actual owner'):
            with self.subTest(phrase=phrase):self.assertIn(phrase,docs)

    def test_completion_requires_documentation_impact_even_when_not_applicable(self):
        behavior=text('skills/workflow-contracts/behavior.md')
        for phrase in ('Doc impact:','not applicable: <reason>',
                       'changed paths','validation','omitted disposition remains incomplete'):
            with self.subTest(phrase=phrase):self.assertIn(phrase,behavior)
        for name in ('implement','test-review'):
            body=text('skills/'+name+'/SKILL.md')
            with self.subTest(skill=name):
                self.assertIn('Documentation currency',body)
                self.assertIn('Doc impact:',body)

    def test_reviewer_finds_staleness_without_becoming_doc_writer(self):
        role=text('skills/agent-coordination/references/independent-reviewer.md')
        for phrase in ('documentation currency','stale/conflicting guidance',
                       'actual owner','not another writer','authoritative guidance changes'):
            with self.subTest(phrase=phrase):self.assertIn(phrase,role)
        self.assertIn('Documentation currency',text('skills/workflow-contracts/decisions.md'))
        from agent_skills import Catalog
        packet=Catalog(ROOT).compose(['company.implement','company.test-review'],role='worker')
        self.assertEqual(sum(s['path']=='skills/workflow-contracts/behavior.md' for s in packet['sources']),1)
        self.assertTrue(any('## Documentation currency' in s.get('content','') for s in packet['sources']))

    def test_actual_connection_mode_is_not_inferred_from_a_flag(self):
        body=text('skills/agent-coordination/references/reviewer-access.md')
        for phrase in ('actual connection start','effective permissions and transaction mode',
                       'connection option alone is not proof','approved isolated canary',
                       'never attempted production writes'):
            with self.subTest(phrase=phrase):self.assertIn(phrase,body)

if __name__ == '__main__':
    unittest.main()
