# Contributing

Keep the core provider-neutral. New AI services should be optional adapters,
must read credentials from environment variables, and must degrade cleanly when
not configured. Do not weaken the human storyboard approval gate.

Run before opening a change:

```bash
python3 -m compileall -q shorts.py pipeline
npm --prefix pipeline/remotion run typecheck
python3 -m unittest discover -s tests -v
```

