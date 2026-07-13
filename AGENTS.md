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
7. Run `python shorts.py status --slug <slug> --json` and inspect both JSON files.
8. Run `python shorts.py board --slug <slug>` and stop. Show the human
   `storyboard/contact-sheet.png` and wait for explicit approval.
9. Never run `approve` merely because the storyboard exists. Approval belongs
   to the human owner. If the storyboard or beat count changes, approval must be
   obtained again.
10. After explicit approval, run `approve`, `gen`, `install`, and `render` in
    that order. Re-run failed scenes with `gen --only N,N`.
11. Inspect the final MP4 at every narration-synced scene midpoint. Check cast,
    duplicate props, unintended text, continuity, captions, duration, audio and
    end card before declaring it ready.
12. Never upload, schedule, publish, or alter a channel setting without a
    separate explicit request from the human owner.

The deterministic final renderer is not an AI agent. Do not replace generated
scene files after approval without reporting that change and performing QA.

