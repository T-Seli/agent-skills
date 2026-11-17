# Model selection
Choose a role first, then a tier. Skills and prompts never name a model id: ids, efforts and timeouts live only in the worker config (`policy.<provider>`), so a new model needs a config edit and no skill edit. Works for any provider the config lists.

## Roles and tiers
| Role | Default tier | Why |
|---|---|---|
| planner (plan, design, brainstorm, grill) | involved | open-ended reasoning; a wrong plan costs every later step |
| reviewer, judge | involved | independent of the builder; high blast radius |
| builder (implement a scoped ticket) | ordinary | clear scope, tests decide |
| scout (read-only lookup) | ordinary | bounded question, capped answer |

Config: `policy.<provider>.roles` maps role to tier; `ladder` orders tiers weakest to strongest (default `ordinary`, `involved`; add middle tiers freely). An unlisted role uses the signal rule in worker-execution.md § Select and pin.

## Inputs that move a task up a tier
Unclear scope, non-deterministic or ambiguous failure, large blast radius (shared state, production, security, many systems), then cost and latency as tie-breakers: pick the weakest tier whose failure the task's tests or reviewer would catch. Effort comes from the tier profile and never exceeds `effort_ceiling`.

## Escalation
Pass the count of failed or blocked attempts as `failures`; every two climb one tier (`select_route(..., role=..., failures=n)`). At the top of the ladder it raises: report blocked with the attempts. Never fall back to a weaker tier or another provider silently.

## Verify
Record the route with `record_execution` and compare it with the model and effort the runtime reports; a mismatch is a blocker, not a note.

## Layers
One config file per run: `AGENT_SKILLS_CONFIG` selects it (user file by default, a project file when set). Merging global with project files is not implemented; a project file must be complete.
