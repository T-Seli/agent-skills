# Visualization decisions

Use only for charts, dashboards and interactive explanations; ordinary forms do
not need a chart. State the question and the decision the visual should support.
Use a table or concise text when it communicates better. Use the actual installed
visualize capability for in-conversation exploration; discover and read its skill
first. For export/share/publication-quality scientific output, use the appropriate
standard plotting/document workflow. Do not add a renderer or UI runtime here.

## Data and honest comparison

Record source/provenance, access date, units, denominator, population, timeframe,
timezone, aggregation and transformations. Distinguish real, sampled and synthetic
data; use sanitized realistic fixtures without exposing customer information.
Mark missingness, exclusions, sample size and uncertainty. Missing data is not
zero; zero activity is not proof of success. Explain bounds and assumptions.
For diagrams/simulations, label assumed relationships and model limitations.

Choose visual encodings for the question: comparison, change over time,
distribution, relationship or location. Compare alternatives using identical data,
units, scale and timeframe; explain an intentional difference. Label axes and
baselines, avoid misleading truncation and decorative depth, and use readable
ordering and meaningful precision. Do not imply causation from association.

For interactions, retain a legible initial view; label controls, filter scope and
reset behavior. Show active filters and units; make calculations reproducible.
Expose tooltips and actions to keyboard/focus, not hover alone. Essential meaning
must remain available without animation, pointer precision or color vision.
Provide accessible text/table alternatives, readable contrast and non-color cues.
Dynamic charts must respect reduced motion and preserve context on updates.

## Evidence, options and verification

Carry the question/data contract through the UI design packet. Offer distinct
useful views, not ornamental variants; explain their strengths and what they hide.
Render representative sparse/dense/empty/uncertain data and compare displayed
values with the source or an independent calculation. Verify mobile/zoom,
keyboard use, labels, filter/reset logic and the accessible alternative. Retain
exact artifact/revision, fixtures, source and actual check receipts. A persuasive
chart is not verification of data truth, accuracy or user comprehension.

Starting guidance inspected 2026-11-07; publication/revision not shown:
- [ONS visualization guidance](https://service-manual.ons.gov.uk/data-visualisation/guidance): chart choice, text, axes, uncertainty and accessible presentation in official statistics.

Read the relevant linked topic dynamically for the current question, alongside
applicable accessibility/platform guidance. ONS's publishing context and house
style may differ from this product. Treat examples as hypotheses, record conflicts
and limitations, and validate local fit instead of copying charts blindly.
