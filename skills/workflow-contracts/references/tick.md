# The belt tick: scheduled-task definition

Status: not registered. This file is the definition only; nothing runs until the owner registers it. Conveyor rules stay in [conveyor.md](../conveyor.md); numbers live in conveyor.json `tick` and contracts.md § Defaults.

## The tick prompt
Run every 15 minutes (conveyor.json `tick.cadence_minutes`) by a small, cheap model with the project as its working directory. The prompt:

```
Run: ~/.agents/skills/workflow-contracts/scripts/issues-cli belt-tick --repo <owner/repo>
It sweeps, lists the inbox, reports `Pull next:`, dispatches and prints one `Tick:` line.
For each item under `Inbox to sort`, read its text and pick one domain, one kind and one size
from the `Allowed:` line. Then run:
  issues-cli sort --repo <owner/repo> <n> --domain <d> --kind <k> --size <s>
When unsure of any value, add --needs-decision instead of guessing.
You never publish, merge, deploy or send anything, and never ask the owner a question.
On any refusal or `step failed:` line, stop and report that line as it is.
End with the `Tick:` line and one line per sorted item.
```

## Why this shape
- The command does every fixed step; the model only judges the sort. A rule, count or check is a script.
- A failed step is reported and independent steps still run; `pull` waits on the sweep.
- `--dry-run` makes every step read-only, so a trial run changes nothing.

## First week
Machine `workers.json` `dispatch` sets `build_cap_override` 3 and `sizes_allowed` S only. Dispatch refuses a start when the data volume has under 10 GB free.

## Register later
The owner creates the scheduled task from the prompt above in the desktop app at the cadence in conveyor.json. It is not registered yet; no session registers it.
