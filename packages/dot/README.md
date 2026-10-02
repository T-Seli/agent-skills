# Dot adapter — proposed

There is no verified Dot skill-install API or local package target in this
repository. Do not map the Claude or Codex installer to Dot by guesswork. A Dot
adapter must be built against its supported interface, with its own consent
and reply-routing tests, before it can be installed. `install.sh` rejects Dot.

The authored workflow contract is [workflow.md](workflow.md). It is reviewable
source material, not an installed Dot skill or an automatic message bridge.

The [cloud-first session ownership proposal](session-ownership-proposal.md)
defines the review gates for worker takeover, resume, and recoverable archive.
