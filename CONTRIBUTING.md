# Contributing

Keep the production flow reproducible. New AI services must be optional
adapters, read credentials from environment variables, preserve reference-image
continuity and never weaken the human storyboard approval gate.

Run before opening a change:

```bash
python3 -m compileall -q shorts.py pipeline
npm --prefix pipeline/remotion run typecheck
python3 -m unittest discover -s tests -v
```
