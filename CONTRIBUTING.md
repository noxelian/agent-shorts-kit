# Contributing

Keep the production flow reproducible. New AI services must be optional
adapters, read credentials from environment variables, preserve reference-image
continuity and never weaken the human storyboard approval gate.

Run before opening a change:

```bash
./.venv/bin/python -m compileall -q shorts.py pipeline tests
npm --prefix pipeline/remotion run typecheck
./.venv/bin/python -m unittest discover -s tests -v
```

Do not commit generated episodes, credentials, tokens, private references,
release manifests, music, or unpublished media. Changes to approvals,
provenance, QA or upload logic must include a regression test proving stale
inputs or artifacts remain blocked.
