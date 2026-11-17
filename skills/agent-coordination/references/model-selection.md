# Model selection
Choose a role first, then a tier. Skills and prompts never name a model id: ids, efforts and timeouts live only in the worker config (`policy.<provider>`), so a new model needs a config edit and no skill edit. Works for any provider the config lists. Logic adopted from the model-selection guidance Thomas supplied (Nov 2026): difficulty over spec clarity, effort before model, escalation order, low-effort-then-rerun, cost per task.

## Roles and tiers
| Role | Default tier | Why |
|---|---|---|
| planner (plan, design, brainstorm, grill) | involved | open-ended reasoning; a wrong plan costs every later step |
| reviewer, judge | involved | independent of the builder; high blast radius |
| builder (implement a scoped ticket) | ordinary | clear scope, tests decide |
| scout (read-only lookup) | ordinary | bounded question, capped answer |

Config: `policy.<provider>.roles` maps role to tier; `ladder` orders tiers weakest to strongest (default `ordinary`, `involved`; add middle tiers freely). An unlisted role uses the signal rule in worker-execution.md § Select and pin.

## Inputs
Difficulty decides the tier, not spec clarity: a clear spec can still be a migration or performance task. Smaller tiers fit checkable, high-volume or side work (lookups, classification, log reading) where a wrong answer is cheap to spot, and fit long dependent agent loops less. Strong tiers take open-ended planning, architecture, large blast radius (shared state, production, security, many systems) and leading others. Cost and latency break ties: weakest tier whose failure the task's tests or reviewer would catch; compare cost per finished task, not per token. Edits and judgment stay on the stronger tier when it leads; delegate verbose reading to the smaller one. Let code, not a model, route when the rule is this simple.

## Effort
Effort comes from the tier profile and never exceeds `effort_ceiling`. Raise effort before the model, and give the builder a way to verify its own work (test, build, script) before either. A cheap pass with automatic checks, rerunning only failures higher, beats running everything high.

## Escalation
Order: make the work self-verifying, raise effort one level within the ceiling, then climb one tier at the lower effort. Code covers the tier step: pass `failures` (failed or blocked attempts); every two climb one tier (`select_route(..., role=..., failures=n)`). At the top of the ladder it raises: report blocked with the attempts. Never fall back to a weaker tier or another provider silently. Switch tiers at a natural break (short written plan or compaction), since caches belong to one model.

## Verify
Record the route with `record_execution` and compare it with the model and effort the runtime reports (usage output); a mismatch is a blocker, not a note. Measure candidates on the task's own work, each in its own session.

## Layers
One config file per run: `AGENT_SKILLS_CONFIG` selects it (user file by default, a project file when set). Merging global with project files is not implemented; a project file must be complete.
