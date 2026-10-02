# Deploy modes

Read only the mode that applies. Bold step names are the steps in `SKILL.md`. Every mode reads the runbook (**Read the runbook**), runs the **Preflight** checks that apply, prints its plan (≤6 lines) and proceeds once there is a go-ahead (contracts.md § Consent), logs per contracts.md, and ends with the SKILL.md report, dropping lines that don't apply.

## PR (args `PR` only: the user asked for a PR)
1. **Review**, **Checkout** and **Base**, then the plan.
2. Make the **Record** commit on the task branch (entry `deploy: PR → <base>`, no targets yet; no push to `<base>`), then `git push -u origin <branch>` and delete the carried draft logs.
3. Open a PR against `<base>` with § Map's git host CLI, body drawn from the log.
4. **Rechecks**, with a prompt that says to first find the merge on `<release>` by its PR number or merge commit (a squash merge leaves no branch sha there), then check the targets.
No lock, deploy, cleanup or quick check.

## Local (no remote)
Refs are local: `<base>` stands for `origin/<base>` in every check.
1. **Task**, **Checkout**, **Review** (over `<base>..<sha>`), **Targets**, then the plan.
2. Fast-forward `<base>`: branch flow `git -C <worktree that has <base>> merge --ff-only <sha>`; trunk flow `<base>` is already there.
3. **Deploy** and **Verify** each target, one at a time. A failed target: as in SKILL.md.
4. **Record** on `<base>` in that worktree, committing only the log files (`git commit -- <paths>`); no push.
5. Branch flow: **This task** (merged = into local `<base>`).
6. **Chain to monitor** for the quick check only.
No push or rechecks (contracts.md § Names); release a trunk-flow `LOCK` this agent holds.

## Release (args `release`; for § Deploy `Release: batched`)
Ships everything merged to `<base>` since the last release: a tag, a registry publish, an app-store submission.
1. **Last release**: per § Deploy (e.g. `git describe --tags --abbrev=0 origin/<release>`). Tasks in this release: folders with files added on `origin/<base>` since then (`git diff --name-only --diff-filter=A <last>..origin/<base> -- ':(top)<tasks>'`), skipping monitor-only folders. `<tasks>` is `none`: list the commits instead.
2. **Lock**, **Targets** and **Recheck times**; the plan names the release, its tasks, each target and its rollback ref. Then **Lock**.
3. Tag, publish or submit per § Deploy. Then **Deploy** and **Verify** each target (the reported version maps to a commit that contains the release commit), one stage at a time. A failed target: as in SKILL.md.
4. **Rechecks** for each included task, then **Record**: one record commit appending `deploy: release <name> to <targets>` (with `Rollback:`, `Scheduler:` and Watch for) to each included task's `log.md`.
5. **Release the lock**, then **Chain to monitor**.

## Rollback (args `rollback`)
The user's "rollback" is consent for this step per contracts.md § Consent; a failed target's kept `LOCK` is yours to reuse.
1. `git fetch origin`. Find the last deploy (contracts.md): in the folder named in args, else across `<tasks>/*/log.md` on `origin/<base>`. Headings sort by time: `git grep -h -e '— deploy: ' origin/<base> -- ':(top)<tasks>' | sort` lists them oldest first; take the newest whose entry has a `Rollback:` line, and find its folder with `git grep -l -F '<that heading>' origin/<base> -- ':(top)<tasks>'`. Also read `DRAFT/log.md`: a failed target's entry there is newer. `<tasks>` is `none`: search `$MAIN/.claude/drafts/*/log.md` instead.
2. If § Deploy has a `Kill switch` that covers this change, name it in the plan as the lighter option and use it only if the user's go-ahead names it. Rollback is `forward-fix only`: stop, say so, and suggest `/blueprint` for the fix.
3. **Lock**, then print the plan (each target and its ref), roll each target back per § Deploy, and check each with **Verify** (its version maps to the rollback ref). A target fails to roll back: stop, keep `LOCK`, report.
4. Append `deploy: rollback to <refs>` to `DRAFT/log.md` for that folder (the next `/deploy` carries it), then **Release the lock**.
5. `<base>` still holds the change, so the next deploy re-ships it: say so and suggest reverting its merge on `<release>` (after a squash merge, the squash commit, not the branch shas) through `/blueprint`.
