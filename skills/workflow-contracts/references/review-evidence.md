# Review and observation evidence

Reuse current task/state, issue and work-trace contracts. One accountable umbrella
owner is separate from execution, review and history writers; a blank assignee
never authorizes replacing that owner. Preserve exact artifact/spec/decision and
combined candidate identities, component owners and excluded work. Keep preparation,
implementation, release/activation and natural behavior acceptance gates separate;
ready labels, merge and closed dependencies do not prove deployed dependencies.
Hold dependent activation while continuing independent authorized preparation.

## Requested versus actually observed

Bind each source receipt to requested and observed interval, source observation
time, source/runtime identity, cap/truncation, state (verified/failed/blocked/unknown)
and freshness bound. Preserve raw receipt references and coverage limits. A capped
five-second sample cannot certify a requested fifteen minutes. A task read, wake,
local preflight or rendered status does not renew source freshness. Keep scheduling
activity separate from coverage; existing monitor ownership does not change.

`monitoring_verdict(..., coverage=...)` and existing watch-result/readback paths use
`observation_evidence.assess_coverage`. The packet has `requested`/`observed`
`{start,end}`, `source_observed_at_utc`, `source_identity`, `runtime_identity`, `state`,
`cap_seconds` (null when uncapped), `truncated`, `max_source_age_seconds`, `receipt_ref`.
Dates are timezone-aware; bounds/pins come from the actual read and agreed scope,
not values invented to pass validation. Missing legacy coverage remains unknown;
positive receipts without it no longer establish functional acceptance. Callers
must explicitly supply source evidence; there is no automatic sampler or adoption.
Complete metadata is not authenticated evidence. Partial observed failures are
check failures, not proof of a causal incident or full-window health. Unavailable,
stale or truncated evidence cannot yield a healthy full-window verdict; zero
traffic cannot close natural acceptance. An error-word count needs context and
corroborated source evidence before an incident or cause is asserted.

## Findings through acceptance and learning

Use one stable finding/fingerprint and existing owner/queue. Distinguish prepared,
delivered, acknowledged, dispositioned and verified-resolved; record the closure
test, exact artifact, later replies and still-open natural acceptance. A local
packet, acknowledgment or merge cannot close another owner or wider window.
Review prior improvements against actual consumer/runtime use and observed outcomes,
not text, installation or lack of a repeat in a small sample. Keep authorization,
capability and source/evidence gaps separate. No replacement worker or repeated
notification without changed evidence or a meaningful deadline; notifications still
need actual authority. Installed source without consumer use is adoption unknown.

For cache/cost claims trace fill, read, invalidation and actual runtime consumers.
A cache with no fill path cannot support savings. Separate skipped from passed
checks and reported teammate claims from verified facts. Reuse source/base/toolchain
receipts only after an explicit identity/dependency comparison; component passes do
not certify a changed combined candidate. Review falsifiable correctness, repeated
reliability, safety and latency/cost/rework evidence before claiming improvement.

Repository-qualified links retain actual owner/repo; inspect rendered destination
and native metadata where supported. A misrendered link is a traceability finding,
not proof the wrong code executed. Reads and findings grant no write authority.
