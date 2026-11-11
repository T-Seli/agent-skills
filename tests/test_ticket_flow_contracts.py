"""Big implementations: grill-me → spec → tickets → one worker per ticket → two-axis review → one fixer."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
def text(path): return (ROOT / path).read_text(encoding='utf-8')
CONTRACTS = 'skills/workflow-contracts/contracts.md'
SPEC_MODE = 'skills/implement/references/spec-mode.md'


class BigImplementationChain(unittest.TestCase):
    def test_chain_defines_big_implementation_and_routes_it(self):
        chain = text(CONTRACTS).split('## Chain', 1)[1].split('## Consent', 1)[0]
        line = next(x for x in chain.splitlines() if '**big implementation**' in x)
        for step in ('the user or the kickoff brief calls it one', 'grill-me before the plan is written',
                     'action-items as tickets', 'spec mode', 'spec-mode.md'):
            self.assertIn(step, line)
        self.assertIn('**tdd**', chain)

    def test_grill_and_blueprint_hand_seams_to_the_spec(self):
        self.assertIn('test seams', text('skills/grill-me/SKILL.md'))
        blueprint = text('skills/blueprint/SKILL.md')
        self.assertIn('runs `/grill-me` first', blueprint)
        self.assertIn('stop and grill before any architect runs', blueprint)
        verify = next(x for x in blueprint.splitlines() if x.strip().startswith('## Verify'))
        self.assertIn('Seams (big implementation):', verify)


class Tickets(unittest.TestCase):
    def test_tickets_are_vertical_single_context_slices_with_edges(self):
        items = text('skills/action-items/SKILL.md')
        block = items.split('**Tickets**', 1)[1].split('\n7. ', 1)[0]
        for rule in ('`Tickets: <n>`', 'tracer bullet', 'one fresh worker context', 'No L tickets',
                     'blockers first', 'acceptance checkboxes', 'Prefactoring'):
            self.assertIn(rule, block)
        self.assertIn('are the blocking edges right, and should any be merged or split', items)


class SpecMode(unittest.TestCase):
    def test_implement_enters_spec_mode_and_never_shares_a_worktree_for_tickets(self):
        implement = text('skills/implement/SKILL.md')
        self.assertIn('references/spec-mode.md', implement)
        mode = next(x for x in implement.splitlines() if x.startswith('**Spec mode**'))
        self.assertIn('in place of **Loop**', mode)

    def test_one_worker_per_ticket_off_the_integration_branch(self):
        spec = text(SPEC_MODE)
        for rule in ('integration branch', 'worktree add --no-track -b <type>/<slug>-t<N>',
                     'pointers rather than pasted text', 'Run `/tdd` for ticket', 'Merge the integration tip',
                     '**merger**', 'Frontier', 'dispatch newly ready tickets', '**one fixer**',
                     'references/review-axes.md', 'reads no worker diffs', '`/handoff`',
                     '--task-id <slug>-t<N> --contract-file', 'take `LOCK`', 'git branch -d', 'without `--force`',
                     'test-review NO inside the plan', 'red then green', 'git worktree unlock',
                     'never removed', 'ask the starter'):
            self.assertIn(rule, spec)
        defaults = text(CONTRACTS).split('## Defaults', 1)[1]
        line = next(x for x in defaults.splitlines() if x.startswith('- Spec mode:'))
        self.assertIn('ticket brief ≤15 lines', line)
        self.assertIn('worker receipt ≤150 words', line)

    def test_review_runs_two_unranked_axes_in_parallel(self):
        review = text('skills/implement/references/review-axes.md')
        for rule in ('## Standards', '## Spec', 'in parallel, in one message', 'Do not merge or rerank',
                     'always a judgement call', 'scope creep', 'test-review stays the gate'):
            self.assertIn(rule, review)

    def test_worker_briefs_point_rather_than_paste(self):
        brief = text('skills/agent-coordination/references/worker-execution.md')
        self.assertIn('point to readable files', brief)
        self.assertIn('one per ticket in implement spec mode', brief)


class Roles(unittest.TestCase):
    def test_each_role_starts_only_the_next_and_workers_never_message_up(self):
        roles = text('skills/agent-coordination/SKILL.md').split('## Roles for big implementations', 1)[1].split('\n## ', 1)[0]
        for rule in ('**Orchestrator assistant (cross-task executive):**',
                     'does not own technical preparation/specs or dispatch ticket workers',
                     'consolidates ready user-facing questions from the owning worker per decisions.md',
                     'preserves original answers on the chosen surface',
                     '**Starter:**', 'at most one live orchestration session', 'successor starts only from', 'paste-ready kickoff brief',
                     '**Orchestration session**', 'Claude or Codex', '`/implement` spec mode',
                     'never message the assistant or the user'):
            self.assertIn(rule, roles)


class TestFirst(unittest.TestCase):
    def test_tdd_loop_rules(self):
        tdd = text('skills/tdd/SKILL.md')
        for rule in ('agreed seams', 'fail on an assertion', 'is not red', '**Horizontal:**',
                     '**Tautological:**', 'Refactoring is not part of the red → green cycle', 'Criteria:'):
            self.assertIn(rule, tdd)
        caps = text(CONTRACTS).split('## Report', 1)[1].splitlines()[1]
        self.assertIn('tdd 5', caps)


if __name__ == '__main__':
    unittest.main()
