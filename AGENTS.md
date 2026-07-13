# Instructions for AI agents

This repository uses a filesystem protocol. Do not add provider credentials to
source files and do not approve a storyboard on behalf of the human owner.

For an episode named `<slug>`:

1. Read `episodes/<slug>/request.json` and `contracts/episode.schema.json`.
2. Write `episodes/<slug>/episode.json` that satisfies the schema.
3. Create `voice.mp3` from `episode.narration`, using credentials or tools that
   belong to the user. Do not copy a third party's voice without permission.
4. Prefer real word timestamps in `words.json`. If unavailable, run
   `python shorts.py captions --slug <slug>`.
5. Create exactly one `scenes/scene_N.png` per scene. Use 1080x1920 unless the
   project config says otherwise. Do not place captions or watermarks inside
   scene images.
6. Run `python shorts.py validate --slug <slug>` and fix every error.
7. Run `python shorts.py board --slug <slug>` and stop. Tell the human to review
   `storyboard/contact-sheet.png`.
8. Only after the human explicitly approves, the human (or agent in that same
   explicit turn) may run `approve`, followed by `render`.

Machine-readable progress is available through:

```bash
python shorts.py status --slug <slug> --json
```

Never run `upload.py` unless the user separately asks to upload. Default any
requested upload to private unless the user explicitly chooses otherwise.

