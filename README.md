# Agent Shorts Kit

An AI-provider-neutral production kit for vertical Shorts. Your AI agent makes
the creative decisions and assets; this repository validates the contract,
requires human storyboard approval, and renders a reproducible 9:16 video.

No API key is bundled or required. Generated episodes, OAuth files, tokens,
music, mascot assets and `.env` files are git-ignored.

An optional non-interactive script command can be connected with
`SHORTS_AGENT_COMMAND="your-agent-command"`; it receives the prompt on stdin
and must print episode JSON on stdout. The documented filesystem workflow is
more portable and works with interactive coding agents.

## What it gives you

- a machine-readable episode contract;
- an agent-friendly `request.json` and `status --json` interface;
- a mandatory `board -> approve -> render` safety gate;
- word-timed captions, motion, transitions and optional SFX/music;
- a Remotion renderer that produces `episodes/<slug>/out/final.mp4`;
- optional provider adapters that only run with the user's own credentials.

## Requirements

- Python 3.11+
- Node.js 20+
- `ffmpeg` and `ffprobe`

## Install

```bash
python3 -m venv .venv
./.venv/bin/pip install -r pipeline/requirements.txt
npm --prefix pipeline/remotion ci
./.venv/bin/python shorts.py doctor
```

The default file contains only renderer/validation dependencies. To use the
optional built-in TTS, alignment, FAL and parallax adapters, install
`pipeline/requirements-ai.txt`. The YouTube uploader has its own
`pipeline/requirements-youtube.txt`.

## Bring your own AI agent

```bash
./.venv/bin/python shorts.py init \
  --topic "Why the shortest war lasted only 38 minutes" \
  --slug shortest-war
```

Then ask any coding/AI agent:

> Read AGENTS.md, complete episode `shortest-war`, and stop after creating the
> storyboard. Do not approve or render it for me.

The agent fills these owner-local files:

```text
episodes/shortest-war/
  request.json
  episode.json
  voice.mp3
  words.json
  scenes/scene_1.png ... scene_N.png
```

If the voice provider did not return word timestamps, create safe uniform
timings from the known narration and measured audio duration:

```bash
./.venv/bin/python shorts.py captions --slug shortest-war
```

Review and approve explicitly:

```bash
./.venv/bin/python shorts.py board --slug shortest-war
# open episodes/shortest-war/storyboard/contact-sheet.png
./.venv/bin/python shorts.py approve --slug shortest-war
./.venv/bin/python shorts.py render --slug shortest-war
```

Approval is bound to the SHA-256 of the contact sheet and the exact scene
count. Rebuilding or changing the board invalidates approval.

## Useful commands

```bash
python shorts.py status --slug shortest-war --json
python shorts.py validate --slug shortest-war
python shorts.py demo --slug demo
python shorts.py render --slug shortest-war --force
```

`demo` creates synthetic local assets without AI or network credentials. It
still needs installed dependencies to render the final MP4.

## Security and publishing

Uploads are intentionally separate from rendering. The optional YouTube
uploader defaults to `private` and requires a user-created OAuth desktop file.
Never commit `pipeline/credentials.json`, `pipeline/token.json`, `.env`, or an
episode directory. See `SECURITY.md` before publishing a fork.

## Scope

This repository is the production engine, not a promise of viral performance.
Users remain responsible for factual review, rights to images/music/voices,
platform disclosure, and final publication. Third-party licenses and service
terms are summarized in `THIRD_PARTY.md`.
