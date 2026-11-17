# Before/after approval pairs
Approval views are never files: SendUserFile or attachments may not render for the user.
1. Publish the pair page as a private Artifact link. Numbered items, BEFORE and AFTER per item, one-line description, images embedded as `data:` URIs, light and dark themed. Build it with `python3 ${CLAUDE_SKILL_DIR}/scripts/build_pairs.py spec.json out.html`; spec: `{"title","intro","items":[{"n","name","what","before","after"}]}`, before/after are PNG paths.
2. The coordinator asks ONE pair per native question (AskUserQuestion), quoting the link and pair number, recommended option first.
3. Show a UI notice only when critical; prefer backend hardening so none is needed.
4. A worker producing pairs saves the PNG pairs and the spec JSON for the coordinator, or publishes the Artifact itself.
