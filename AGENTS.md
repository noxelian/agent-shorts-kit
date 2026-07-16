# Production instructions for AI agents

This repository packages a human-approved production workflow. Never put API
keys, Google project credentials or OAuth tokens into tracked files.

For `episodes/<slug>`:

1. Read `request.json`, `contracts/bits.schema.json`, and
   `contracts/episode.schema.json`.
2. Research the topic from reliable sources. Keep a source list in the episode
   workspace and separate verified facts from speculation.
3. Replace all placeholders in `episode.json`. The narration must be the exact
   final spoken text and should fit the configured target duration.
4. Replace all placeholders in `bits.json`. Split narration into 12–20 short,
   sequential visual beats. Every `vo` must be a verbatim contiguous segment of
   narration and all beats together must cover it in order.
5. Make `world` explicit: recurring identity, clothing, props, location,
   palette, period, prohibited characters/objects and continuity rules.
6. Use location anchors for recurring sets when needed:
   `location`, plus `location_anchor: true` on the canonical first view.
7. Run `python shorts.py validate --slug <slug>` before any paid generation.
   Never bypass validation or weaken it to make an incomplete plan pass.
8. Run `python shorts.py status --slug <slug> --json` and inspect both JSON files.
9. Run `python shorts.py board --slug <slug>` and stop. Show the human
   `storyboard/contact-sheet.png` and wait for explicit approval.
10. Never run `approve` merely because the storyboard exists. Approval belongs
   to the human owner. If the storyboard or beat count changes, approval must be
   obtained again.
11. After explicit approval, run `approve`, `gen`, `install`, and `render` in
    that order. Re-run failed scenes with `gen --only N,N`.
12. Run `python shorts.py qa --slug <slug>`. Inspect both the automated report
    and `qa/midpoints-contact-sheet.jpg`; automation does not replace visual
    judgment about cast, duplicate props, unintended text or continuity.
13. Create a release package only after QA passes. Show the human
    `publish-package.md`, final SHA-256, duration and target slot.
14. Never run `approve-release` merely because QA passed. That command is a
    separate human decision and must name the intended privacy level.
15. Never upload, schedule, publish, or alter a channel setting without a
    separate explicit request from the human owner.

The deterministic final renderer is not an AI agent. Do not replace generated
scene files after approval without reporting that change and performing QA.
Never edit `approved.json`, `build-manifest.json`, `qa-report.json`, or
`release-approved.json` by hand; use the CLI so their hashes remain meaningful.
