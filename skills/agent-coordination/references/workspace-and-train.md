# Keep the workspace clean and run the draft-PR release train

Duties of an engineering coordinator ([coordinator-mode](coordinator-mode.md)). Keys below are defaults; a project overrides one in its `CLAUDE.md` § Defaults with the same label.

## Keep the workspace clean
With `Auto-archive: on` (user's standing approval; default `off`), archive a session this coordinator started once its outcome is complete and verified: PR merged and deployed, or a read-only deliverable consumed. Never archive a user-owned or user-kept session, or one with an open PR, running work, unmerged commits or an unconsumed result. A session that meets the rule needs no per-session ask; report one line: archived <name> (<evidence>). With `Auto-archive: off`, propose the batch instead.

After each release, run the deploy sweep (clean, merged, unheld worktrees; merged local branches; prune), then print `df -h /`; below `Disk free floor` (default 20 GB) flag it to the user. Before starting a worktree session, require `Worktree start free` (default 10 GB warn, 5.4 GB hard stop): warn and run the sweep first, and below the hard stop start nothing and say why. Dirty, unpushed, locked, live or held resources stay untouched; no force.

## Run the draft-PR release train
With `Draft train: on` (the user's opt-in; default `off`; this is the scheduled draft-review policy that hosted-review.md reserves), every `Train cadence` (default 4 hours) the coordinator reviews all open draft PRs of the repo except those on `Train NO list` and `Train hold list`, and reports. Per PR: read the diff and linked issue; trial-merge against the base in a temporary detached worktree (removed after); run the test diff only if no result exists for its head and fewer than `Test slots` (default 2) runs are live; classify READY (clean, reviewed, no conflict), NEEDS REFRESH (conflict or stale base: files and fix), BLOCKED (failing names or open decision), or NEEDS APPROVAL (UI or copy the user must see). List base commits by others since the last recorded deploy, so nothing merged is unreleased unnoticed.

The coordinator only reads and reports. Refreshing a branch, merging a READY PR into the release branch (merge commit, behavior.md § Release train) and marking the release PR ready go through that PR's worker with the user's pasted approval line; a member PR stays draft, and only the release PR is marked ready. The coordinator never merges to the base, deploys, posts a verdict, cancels a check or touches a PR on a list. Merge and deploy lines come only from the user, after the previous release is verified.

One line per run: `Train <time>: <n> drafts · <r> ready · <f> refresh · <b> blocked · <u> unreleased base commits · release PR <#>: <members> · disk <GB> · Need: <exact approval line | none>`; details go in the task record, never a new tracker.
