"""`issues-cli park`, `unpark`, the sweep's un-park and stall, and dispatch's skip of both (conveyor.md § Flow).
gh, the clock and delegate are stubbed: nothing is started or written outside the fake."""
import re
from datetime import timedelta

from agent_skills import issues_cli
from test_issues_cli import REPO
from test_issues_cli_conveyor import BUILDER, CONVEYOR, TIMELINE, BeltCase
from test_issues_dispatch import DispatchCase

PARKED = re.compile(CONVEYOR['receipts']['parked']['pattern'])
UNPARKED = re.compile(CONVEYOR['receipts']['unparked']['pattern'])
STALLED = re.compile(CONVEYOR['receipts']['stalled']['pattern'])
MARKER = re.compile(CONVEYOR['dispatch']['marker']['pattern'])
LIMITS = '- Lane limits: Build 1 (0 kept free for `prio:now`, at most 1 size M) · Review 1 · Investigate 1 · Release 1 train of ≤6 PRs · Sessions 10\n'


class ParkCase(BeltCase):
    def park(self, n, *extra, ok=True):
        return self.cli('park', '--repo', REPO, str(n), *extra, ok=ok)

    def park_for(self, n, until='2026-11-20', why='waiting on the vendor', *extra, ok=True):
        return self.park(n, '--until', until, '--why', why, *extra, ok=ok)

    def line(self, n, pattern):
        return [m for x in self.gh.lines(n) if (m := re.match(pattern, x))]


class Park(ParkCase):
    defaults = LIMITS

    def test_park_writes_the_hand_over_labels_it_and_releases_the_session(self):
        n = self.at('in-progress')
        out = self.park_for(n, '2026-11-20', 'waiting on the vendor', '--done', 'schema', '--left', 'the form', '--next', 'ask the vendor')
        self.assertIn(f'#{n} parked until 2026-11-20', out)
        [m] = self.line(n, PARKED)
        self.assertEqual((m['why'], m['until'], m['time']), ('waiting on the vendor', '2026-11-20', '2026-11-18 12:00Z'))
        lines = self.gh.lines(n)
        self.assertIn('Done: schema', lines)
        self.assertIn('Left: the form', lines)
        self.assertIn('Next: ask the vendor', lines)
        self.assertIn('Branch: `feat/w`', ' '.join(lines))
        self.assertIn('parked', self.gh.names(n))
        self.assertEqual(self.gh.lane(n), 'in-progress')  # a park never moves a lane
        self.assertEqual(self.gh.issues[n]['state'], 'OPEN')
        self.assertEqual(self.gh.timeline(n)[-1]['command'], 'park')
        released = [x for x in self.gh.lines(n) if MARKER.match(x)]
        self.assertEqual(released, [f'<!-- conveyor:v1 released {BUILDER} -->'])

    def test_parking_frees_the_build_slot_and_the_lane_count(self):
        n = self.at('in-progress')
        self.assertTrue(issues_cli.room_missing(self.gh, REPO, 'in-progress', ['prio:now']))
        self.park_for(n)
        self.assertEqual(issues_cli.room_missing(self.gh, REPO, 'in-progress', ['prio:now']), [])
        self.assertIn('in-progress 0/1', self.board(self.sweep(), 'Lanes:'))

    def test_an_event_until_is_accepted(self):
        n = self.at('in-progress')
        self.park_for(n, 'event:vendor-replied')
        self.assertEqual(self.line(n, PARKED)[0]['until'], 'event:vendor-replied')

    def test_refusals_write_nothing(self):
        n = self.at('in-progress')
        self.assertIn('--why', self.park(n, '--until', '2026-11-20', ok=False))
        self.assertIn('--until', self.park(n, '--why', 'x', ok=False))
        self.assertIn('not a date', self.park_for(n, 'someday', ok=False))
        self.assertIn('already passed', self.park_for(n, '2026-11-17', ok=False))
        self.assertEqual(self.gh.writes(), [])
        self.park_for(n)
        self.assertIn('already parked', self.park_for(n, ok=False))
        self.gh.close(n)
        self.assertIn('closed', self.park_for(n, ok=False))

    def test_dry_run_writes_nothing(self):
        n = self.at('in-progress')
        out = self.park(n, '--until', '2026-11-20', '--why', 'x', '--dry-run')
        self.assertIn('gh issue comment', out)
        self.assertEqual(self.gh.writes(), [])
        self.assertNotIn('parked', self.gh.names(n))


class Unpark(ParkCase):
    defaults = LIMITS

    def test_manual_unpark_keeps_the_lane_and_leaves_a_receipt_and_a_timeline_line(self):
        n = self.at('in-progress')
        self.park_for(n)
        self.t += timedelta(hours=1)
        self.cli('unpark', '--repo', REPO, str(n))
        self.assertNotIn('parked', self.gh.names(n))
        self.assertEqual(self.gh.lane(n), 'in-progress')
        [m] = self.line(n, UNPARKED)
        self.assertEqual((m['how'], m['time']), ('manual', '2026-11-18 13:00Z'))
        self.assertEqual(self.gh.timeline(n)[-1]['command'], 'unpark')
        self.assertIn('not parked', self.cli('unpark', '--repo', REPO, str(n), ok=False))

    def test_the_sweep_unparks_when_the_date_has_come_and_not_before(self):
        n = self.at('in-progress')
        self.park_for(n, '2026-11-20')
        self.t += timedelta(days=1)  # 11-19
        self.sweep()
        self.assertIn('parked', self.gh.names(n))
        self.t += timedelta(days=1)  # 11-20
        out = self.sweep()
        self.assertNotIn('parked', self.gh.names(n))
        self.assertEqual(self.line(n, UNPARKED)[0]['how'], 'date')
        self.assertIn(f'- unparked #{n}', out)
        self.assertEqual(self.gh.timeline(n)[-1]['command'], 'sweep')
        self.assertEqual(self.gh.lane(n), 'in-progress')

    def test_the_sweep_unparks_when_the_named_event_receipt_appears_after_the_park(self):
        n = self.at('in-progress')
        self.gh.comment(n, 'Event: vendor-replied')  # before the park: not this wait's event
        self.park_for(n, 'event:vendor-replied')
        self.sweep()
        self.assertIn('parked', self.gh.names(n))
        self.gh.comment(n, 'Event: other')
        self.sweep()
        self.assertIn('parked', self.gh.names(n))
        self.gh.comment(n, 'Event: vendor-replied')
        self.sweep()
        self.assertNotIn('parked', self.gh.names(n))
        self.assertEqual(self.line(n, UNPARKED)[0]['how'], 'event:vendor-replied')

    def test_a_read_only_board_unparks_nothing(self):
        n = self.at('in-progress')
        self.park_for(n, '2026-11-20')
        self.t += timedelta(days=3)
        self.gh.calls.clear()
        issues_cli.board(self.gh, REPO, write=False)
        self.assertEqual(self.gh.writes(), [])
        self.assertIn('parked', self.gh.names(n))

    def test_an_unparked_item_that_was_in_next_is_dispatchable_again(self):
        n = self.at('next')
        self.park_for(n, '2026-11-19')
        self.t += timedelta(days=1)
        self.sweep()
        self.assertEqual(self.gh.lane(n), 'next')
        self.assertNotIn('parked', self.gh.names(n))


class TimeBoxes(ParkCase):
    defaults = LIMITS

    def stalled(self, n):
        return 'stalled' in self.gh.names(n)

    def test_an_s_item_stalls_after_four_hours_without_a_receipt_not_before(self):
        n = self.at('in-progress')  # last receipt 11:30Z
        self.t = self.t.replace(hour=15, minute=30)  # exactly 4 h
        self.sweep()
        self.assertFalse(self.stalled(n))
        self.t += timedelta(minutes=1)
        out = self.sweep()
        self.assertTrue(self.stalled(n))
        [m] = self.line(n, STALLED)
        self.assertEqual(m['since'], '2026-11-18 11:30Z')
        self.assertEqual(self.gh.timeline(n)[-1]['command'], 'sweep')
        self.assertIn(f'Stalled: 1 · #{n}', self.board(out, 'Stalled:'))
        self.assertEqual((self.gh.lane(n), self.gh.issues[n]['state']), ('in-progress', 'OPEN'))  # never moved or closed

    def test_a_new_receipt_restarts_the_box(self):
        n = self.at('in-progress')
        self.t += timedelta(hours=3)
        self.gh.comment(n, f'Conveyor: 2026-11-18 14:30Z · brief · in-progress → in-progress · head - · tests - · skills {"f" * 7} · schedules -')
        self.t += timedelta(hours=3)
        self.sweep()
        self.assertFalse(self.stalled(n))

    def test_an_m_item_has_a_day_and_an_in_review_item_the_same_box(self):
        m = self.at('in-progress')
        self.gh.issues[m]['labels'] = [x for x in self.gh.issues[m]['labels'] if x['name'] != 'size:S'] + [{'name': 'size:M'}]
        r = self.at('in-review')
        self.t += timedelta(hours=23)
        self.sweep()
        self.assertEqual((self.stalled(m), self.stalled(r)), (False, True))
        self.t += timedelta(hours=2)
        self.sweep()
        self.assertTrue(self.stalled(m))

    def test_stalling_frees_the_slot_and_the_lane_count(self):
        n = self.at('in-progress')
        self.t += timedelta(hours=5)
        self.sweep()
        self.assertTrue(self.stalled(n))
        self.assertEqual(issues_cli.room_missing(self.gh, REPO, 'in-progress', ['prio:now']), [])
        self.assertIn('in-progress 0/1', self.board(self.sweep(), 'Lanes:'))

    def test_parked_and_stalled_items_are_not_stalled_again_and_other_lanes_have_no_box(self):
        parked, other = self.at('in-progress'), self.at('next')
        self.park_for(parked, '2026-12-01')
        self.t += timedelta(days=3)
        self.sweep()
        self.sweep()
        self.assertFalse(self.stalled(parked))
        self.assertFalse(self.stalled(other))
        self.assertEqual(len(self.line(parked, STALLED)), 0)

    def test_manual_unpark_clears_a_stall_and_restarts_the_box(self):
        n = self.at('in-progress')
        self.t += timedelta(hours=5)
        self.sweep()
        self.cli('unpark', '--repo', REPO, str(n))
        self.assertFalse(self.stalled(n))
        self.sweep()
        self.assertFalse(self.stalled(n))

    def test_a_read_only_board_names_the_item_past_its_box_and_writes_nothing(self):
        n = self.at('in-progress')
        self.t += timedelta(hours=5)
        self.gh.calls.clear()
        lines = issues_cli.board(self.gh, REPO, write=False)[0]
        self.assertEqual(self.gh.writes(), [])
        self.assertIn(f'- past its time box: #{n} in-progress S', '\n'.join(lines))

    def test_a_card_waiting_on_the_owner_past_its_box_is_in_the_attention_list(self):
        n = self.at('next')
        self.gh.comment(n, f'Conveyor: 2026-11-18 12:00Z · ask · next → next · head - · tests - · skills {"f" * 7} · schedules -')
        self.t += timedelta(hours=3)
        self.assertNotIn('past its box', self.sweep())
        self.t += timedelta(hours=2)
        out = self.sweep()
        self.assertIn(f'- #{n} Widget (asked 2026-11-18 12:00Z, past its 4 h box)', out)
        self.assertIn('Need from you: 1', out)
        self.assertEqual((self.gh.lane(n), 'parked' in self.gh.names(n)), ('next', False))  # a card is flagged, never parked

    def test_the_boxes_come_from_the_contract_not_the_code(self):
        self.root.joinpath('CLAUDE.md').write_text(self.root.joinpath('CLAUDE.md').read_text() + '- Time boxes: Build S 1 h, M 2 days · a card 30 min\n')
        n = self.at('in-progress')
        self.t += timedelta(hours=2)
        self.sweep()
        self.assertTrue(self.stalled(n))


class DispatchSkips(DispatchCase):
    defaults = '- Lane limits: Build 2 (1 kept free for `prio:now`, at most 1 size M) · Review 1 · Investigate 1 · Release 1 train of ≤6 PRs · Sessions 10\n'

    def test_parked_and_stalled_next_items_are_skipped_with_their_reason(self):
        parked, stalled, ok = self.item(), self.item(), self.item()
        self.gh.issues[parked]['labels'].append({'name': 'parked'})
        self.gh.issues[stalled]['labels'].append({'name': 'stalled'})
        out = self.dispatch('--dry-run')
        self.assertIn(f'Skipped: #{parked} parked', out)
        self.assertIn(f'Skipped: #{stalled} stalled', out)
        self.assertIn(f'Would start: #{ok} (build)', out)
        self.assertEqual(self.delegate_calls, [])
        self.dispatch()
        self.assertEqual(len(self.delegate_calls), 1)

    def test_parked_and_stalled_items_free_the_build_and_review_slots_for_dispatch(self):
        self.configure(dispatch={'state_dir': str(self.state), 'build_cap_override': 1})
        self.at('in-progress', labels=('parked',))
        self.at('in-review', labels=('stalled',))
        n = self.item()
        self.gh.issues[n]['labels'].append({'name': 'prio:now'})
        out = self.dispatch('--dry-run')
        self.assertIn(f'Would start: #{n} (build)', out)
        self.assertNotIn('drain', out)
