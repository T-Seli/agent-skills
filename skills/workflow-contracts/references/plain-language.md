# Plain language for customer-facing text

Authority: ASD-STE100 Simplified Technical English (official source: https://www.asd-ste100.org). These rules are our own short summary in our own words. They do not copy the specification or its dictionary; read the official source for the full standard.

## Scope
- Customer-facing text: email drafts, UI and frontend text, client reply drafts, care and lead text drafts, error messages.
- The rules govern drafts and proposed text. They never rewrite a live customer template on their own: its exact wording still needs the owner's approval through the existing approval flow.
- Advice, not a gate. A finding is a reason to reword, never a blocker.

## Rules
1. One idea per sentence. Split a sentence that carries two.
2. Length: procedure sentences about 20 words or fewer, descriptive sentences about 25 or fewer.
3. Active voice, present tense. Name who does the action: "We sent the file", not "The file was sent".
4. Say the action. Use a plain verb, not a noun built from it ("fix", not "perform a fix").
5. One word, one meaning. Pick one word for a thing and keep it in the whole text. Do not vary words for style.
6. No idioms or figures of speech. Use a plain verb where a phrasal verb works ("start", not "kick off").
7. No stacked nouns. A string of three or more nouns hides the relation between them; add small words or split it.
8. Steps in the order they happen, one action per step.
9. Warnings first: put what can go wrong, or what the reader must not do, before the step it affects.
10. Write for a reader who may not read English as a first language and may be stressed or in a hurry.

## Advisory check
`skills/workflow-contracts/scripts/plain-language-check [file]` reads a file or stdin and prints one line per finding: a sentence over its limit, likely passive voice (a heuristic), or filler. It always exits 0. Limits, the filler list and the participle list live in `skills/workflow-contracts/plain-language.json`; change them there, never in the code. It cannot judge idioms, stacked nouns or word consistency: read for those.
