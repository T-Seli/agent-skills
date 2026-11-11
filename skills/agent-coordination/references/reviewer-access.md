# Durable reviewer access

Use existing [data access](../../workflow-contracts/data-access.md) and [roles](roles.md).
Bind every source to the current task, owner, evidence question and permitted scope.
A role, installed connector, remembered grant or successful setup is not effective access.
Research is not provisioning authority; no access or configuration is created here.

## Capability record

Use the existing task/project record, never another queue. Record source/environment,
supported read route, allowed action/resource/data scope, accountable owner,
credential lifetime/renewal method, retention/freshness, last successful bounded
check and exact gaps. Keep private identifiers, account details and secrets outside
shared source. Distinguish discovered, configured, authenticated, authorized,
reachable, verified and degraded; absent receipts remain unknown, not healthy.
MFA-expired or unavailable is not automatically denied; retain the actual result.

## Least privilege and persistence

Prefer renewable short-lived workload credentials with narrow versioned action/
resource allowlists; human interactive identity is separate from unattended identity.
Persist only approved identity/configuration, never raw tokens in prompts, records
or source. Verify renewal, expiry, revocation, audit attribution, host availability
and supported transport independently. Human login does not prove unattended renewal.
Start with inventory, health metrics and sanitized evidence; raw payloads, database
rows, transcripts, encryption-key use and secrets require distinct scoped capability.
Enforce tenancy, redaction and bounded queries at the source; prose is not a control.
Inspect read-named operations for side effects, cost and indirect execution.
Exclude shell/session launch, command dispatch, queue consumption, credential
retrieval, permission changes and production writes unless separately authorized.
A read-like API may alter visibility; never test that against production to find out.

## Separate evidence planes

Cloud infrastructure telemetry, application data, repository evidence and native agent/session state
have different owners and access controls. Cloud permission never unlocks another
host's sessions. Use supported currently authorized surfaces only. Do not switch
identity, host, hidden storage or transport to evade a denial. Missing instrumentation,
retention gaps or masking are coverage limits, not necessarily permission problems.

## Acceptance and operation

Before claiming persistent coverage, verify identity, intended bounded reads,
sanitized output, expiration/renewal, restart recovery and owner-visible failure.
At actual connection start, verify effective permissions and transaction mode through policy analysis and an approved isolated canary; a connection option alone is not proof.
Analyze forbidden actions using policy analysis or an approved isolated canary,
never attempted production writes. Record freshness, sample size and timeframe;
an empty result proves neither health nor coverage. Keep denied, unavailable,
expired and not-yet-tested distinct. Recheck affected evidence on permission,
retention, source-schema or policy drift; widening requires a separate approval.
Report findings and exact gaps through the existing authorized coordinator route.
Provisioning, installation, scheduling and publication retain their own separate approval
and verification gates. This document proves no access was provisioned or renewed.

## Official examples, not provider assumptions

[IAM best practices](https://docs.aws.amazon.com/IAM/latest/UserGuide/best-practices.html)
support temporary workload credentials and least privilege; this does not establish
any particular host's identity mechanism. [SQS ReceiveMessage](https://docs.aws.amazon.com/AWSSimpleQueueService/latest/APIReference/API_ReceiveMessage.html)
documents message visibility effects, illustrating why a read-like name is insufficient.
Rolling documentation inspected 2026-11-11; recheck applicable service/version and
policy before use. These examples grant no AWS or other provider access.
