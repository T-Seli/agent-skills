---
name: ui-design
description: 'Shape UI, frontend and local prototype design with distinct options, product fit and verifiable visual acceptance. Use for UI design, frontend design options or visualization design; pair with blueprint, implement or test-review for that phase.'
---

# UI design

Before any reply, hypothetical or capped included, read these in order:
1. `${CLAUDE_SKILL_DIR}/../workflow-contracts/contracts.md`
2. the governing phase skill, e.g. `${CLAUDE_SKILL_DIR}/../blueprint/SKILL.md`
3. `${CLAUDE_SKILL_DIR}/../workflow-contracts/references/execution-proof.md` (including for non-Git prototypes)
4. `${CLAUDE_SKILL_DIR}/references/design.md`
5. `${CLAUDE_SKILL_DIR}/references/iteration.md`
6. `${CLAUDE_SKILL_DIR}/../workflow-contracts/references/research.md`
This UI supplement alone is not the implementation/review workflow. The reply obeys the smaller of the user's cap and the phase cap (blueprint plan: 12 lines) and a cap overrides every list, evidence or option requirement below: count words and lines of the final text, cut options, rationale and restatement until under both, then send.

For charts, dashboards or interactive explanations also read [visualization](references/visualization.md).
This is a design workflow, not a renderer or implementation engine. Pair with the
actual installed blueprint, implement or test-review skill; its authority and
phase restrictions still apply. Design selection is not implementation consent.

## Start from the product

Identify the user's job, affected surface, actual repository/runtime and phase.
Inspect the existing design system, components, tokens, content, navigation and
current artifact before proposing a replacement. Bind sanitized references and
known constraints to the task. Keep product-specific branding and preferences in
project configuration/specs, outside this shared skill. Preserve familiar layout
unless the user selects a redesign; if the product/reference is unavailable,
label assumptions and the missing evidence rather than inventing its design.

## Explore and choose

Use the design reference to make intuitive, minimal, modern, clean, well-spaced
interfaces concrete: understandable hierarchy, concise copy, purposeful density,
consistent alignment and useful feedback. Minimal means polished, not unfinished;
subtle motion must serve comprehension and respect reduced-motion preferences.
Avoid decorative nested boxes, duplicate controls, unnecessary labels and invented
demo chrome. Keep accessible names, instructions and necessary affordances.

Before choosing a new design, offer two or three genuinely distinct directions
with the same task, content and state coverage, not color-only variants. Include
a least-change direction when improving a product, tradeoffs and a reasoned
recommendation; accept the user's own option. Show proportionate previews when
supported, using the installed visualize capability for in-conversation variants
rather than building another renderer. Missing tools: give labeled wireframes or
an option table and disclose that visual preview is unverified. Do not invoke a
publication or implementation workflow just to show an option.

If the user already selected a direction, preserve it. For a deterministic fix
with no material design choice, record why existing choices suffice instead of
reopening design; never silently omit explicitly requested alternatives.

## Iterate with independent critics

Follow [iterative user-path critique](references/iteration.md): capable independent
subagents interact with the local UI, capture screenshots and critique task
outcomes across at least two rounds. Reconcile findings, improve in authorized
scope and verify fixes on the exact final candidate. Keep stable finding IDs and
actual tool receipts, a bounded convergence rule and explicit missing-capability
gaps; screenshot-only or simulated critique is not interactive verification.

Carry this loop into every UI design plan, spec and handoff, including a short
reply: independent perspectives, real interactions/screenshots, multiple rounds,
findings/fixes and exact-final retests, plus the convergence/hold rule. A hold
must retain open findings/evidence gaps, the responsible owner and next scoped
action. Describe
future gated work when execution is not authorized; a no-worker/no-browser scope
blocks launching them, not explaining the required verification. Shorten option
rationale before dropping this acceptance contract; never imply it already ran.

## One design packet, carried through the work

Keep this in the existing task/spec, not a new tracker:
- Job/audience, surface, source artifact/revision, design-system and runtime fit.
- Map each chosen principle to a user task/state, observable check and evidence limit per the shared execution-proof contract.
- Constraints, research packet/status, inspected sources, conflicting evidence,
  applicability limits and hypotheses to validate with intended users.
- Distinct options/tradeoffs, selected option and authenticated decision reference;
  unresolved choices remain proposed, with owner and held dependent slice.
- Chosen layout, component/token reuse, interaction and content; responsive
  behavior, realistic sanitized fixtures, loading/error/empty/disabled states,
  keyboard/focus, semantics, contrast, zoom/reflow and reduced motion checks.
- Iteration contract: independent critics, user-path/screenshot evidence, rounds,
  stable finding/fix/retest loop and success/budget stopping conditions.
- Exact acceptance artifact, viewport/state matrix, observable checks, human
  accessibility/usability review needs, exclusions and next owner/action.

Blueprint researches and compares options before binding the chosen spec.
Implementation consumes that same packet, uses existing components and builds
only authorized scope; recheck research for drift, not every worker turn.
Review compares the exact rendered candidate and representative interactions
against the selected direction/current product, including narrow screens and
long or missing content. Code review, an HTTP success, a screenshot alone or an
automated accessibility score cannot establish usability or full accessibility.
Report actual checks and limits; human acceptance and release stay separate.

For the offline selector, explicitly compose `company.ui-design` with the phase
skill (at most three skills); a link alone does not load another skill's body or
references. Native hosts read the selected skill and the listed references before replying. Never assume a tool, connector, design library or session route exists.
