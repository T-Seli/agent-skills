# Staged GitHub helper migration

This is local preparation, not an installer or publication grant. Preserve the
currently installed immutable release, live config, schedules and other owners.
Do not create credentials, broaden permissions or run two publishing generations.

1. Inspect existing callers and config without exporting credentials. Verify the
   actual publisher CLI identity with read-only `gh api user` (numeric id/login),
   separately from connector identity; record source and observation time. Derive
   the intended hostname from that host, not from a guessed human or session name.
2. Run the release-bound planner into a new task-local file:

```
~/.agents/skills/workflow-contracts/scripts/github-migration \
  --config <existing-config> --identity <verified-identity.json> \
  --output <new-task-local-plan.json>
```

Identity JSON contains `id`, `login`, `source: "gh api user"` and `observed_at`.
The plan stores hashes and a nonsecret overlay only, never the whole private
configuration or old authorization text. It derives policy from exact review skill,
contract and publisher source bytes. Changed config/policy invalidates the plan.
`apply_to_copy` is a pure fixture/staging operation, not a live config writer.
It preserves unrelated settings, repositories, existing scope and caps.

3. Stage schema v2 in `shadow` mode only. Derive reviewer id, source-bound policy
   and publisher hostname; leave `publication_authorization` blank. The old
   authorization remains historical scope, not permission for more comments.
   `pr_sweep.schema.json` describes the enabled configuration; the example has
   intentionally unresolved placeholders and remains disabled until completed.
4. Migrate issue callers through `ICLI prepare-evidence --repo <repo> --number <n>`
   (or `--draft DRAFT`). It reads exact current body/criteria and emits unverified
   templates; populate actual authority/proof and native `work_record` per [work-trace.md](work-trace.md) from
   inspected coordinator/native source records. Preview unchanged-update suppression
   locally; never publish from the template. Tick only
   the proved subset, refresh after the body changes, and retain independent
   deployment, acceptance and human obligations. Close only the fully eligible
   batch with full deployed SHA and exact-body closure evidence.
5. Migrate review callers to carry the original pending row's full head/base/policy
   through review to `post --sha <head> --base <base> --policy <policy> ...`.
   Never recover a missing reviewed base from the latest remote base. Old saved
   prompts/callers must be checked separately; new SKILL text cannot update them.
6. Run fake-GitHub end-to-end tests: legacy config → conditional overlay → pending
   tuple → local review → shadow post (`posted: false`, no comment). Also exercise
   template → independently populated partial proof → tick → refresh → complete
   closure dry-run. Authenticated legacy same-head verdicts must hold dispatch and
   posting without being accepted as fresh v2 proof; changed heads remain eligible.
   Check stale edits, old callers and publication-mode refusal.
7. Before any activation, establish an owner-approved handover window, reconcile
   existing review work and uncertain posts, and verify saved callers/schedules.
   Do not alter schedules here. Either keep the old release/config untouched or
   arrange an explicitly authorized transition with one publisher generation;
   side-by-side fixtures are safe, parallel live publishers are not assumed safe.
8. Publication requires a separate explicit scoped authorization, reviewed v2
   identity/policy/single-host settings and a supported handover. Start bounded,
   read back actual results, and preserve rollback files. A rollback must reconcile
   any v2 posted/uncertain attempts; reverting code alone does not erase effects.

The shared CI gate holds legacy count-only CCM summaries. The project owner still
needs a complete per-process receipt producer; this migration does not change a
remote workflow or project runner. Missing CI proof holds reuse only, not unrelated
local implementation. No staged fixture or shadow result proves live publication,
monitoring, deployment or subscription savings.
