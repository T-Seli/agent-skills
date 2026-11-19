# Before/after approval pairs
Approval views are never files: SendUserFile or attachments may not render for the user.
1. Publish the pair page as a private Artifact link. Numbered items, BEFORE and AFTER per item, one-line description, images embedded as `data:` URIs, light and dark themed. Build it with `python3 ${CLAUDE_SKILL_DIR}/scripts/build_pairs.py spec.json out.html`; spec: `{"title","intro","items":[{"n","name","what","before","after"}]}`, before/after are PNG paths.
2. The coordinator asks ONE pair per native question (AskUserQuestion), quoting the link and pair number, recommended option first.
3. Show a UI notice only when critical; prefer backend hardening so none is needed.
4. A worker producing pairs saves the PNG pairs and the spec JSON for the coordinator, or publishes the Artifact itself.

## Validate before showing
A prototype, demo or UI mockup reaches the user only after its builder has used it in the browser as a user would. Never show one that has not been checked this way.
- Limits: only under the task's scoped browser authorization (contracts.md § Consent). Interactions stay inside the prototype: never submit, send, delete or buy anything real, never write live data, never type a credential. Close the tabs you opened.
- Open it in the browser tool that drives the user's own browser (Claude in Chrome where installed; its skill's tab rules) and use every interaction; a headless screenshot does not count; check each state (empty, loading, error, long content); for animation, capture several frames; read the console for errors; check narrow width where it applies.
- Fix what you find and check again.
- Record it: `Chrome validation: <URL> · <interactions and states checked> · console <clean | errors> · <screenshots or GIF>`. Show those screenshots or the GIF with the prototype.
