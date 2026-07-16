# Agent Shorts Kit

A reproducible, provider-neutral production workflow for illustrated vertical
Shorts. It is designed to be operated by a human together with an AI coding
agent without giving the agent permission to spend credits or publish freely.

```text
research + script
      ↓ validate (blocks placeholders and narration drift)
episode.json + 12–20 visual beats
      ↓
one Gemini storyboard contact sheet
      ↓ explicit content-addressed human approval
individual scenes + identity/style/location references
      ↓
1080×1920 install → TTS → timestamps → Remotion render
      ↓ sealed build manifest → automated QA → release package
      ↓ explicit release approval → optional YouTube upload → live verification
```

No API key, Google account, OAuth token, episode, unpublished media or private
reference is included.

## Requirements

- Python 3.11+
- Node.js 20+
- FFmpeg and FFprobe
- a Google Gemini API key, or a Google Cloud project with Vertex AI access
- optional ElevenLabs key for the production voice

## Install

```bash
git clone https://github.com/noxelian/agent-shorts-kit.git
cd agent-shorts-kit
./scripts/setup.sh
```

The setup script creates `.venv`, installs the minimal Python dependencies,
installs the locked Remotion packages and creates `pipeline/.env` from the safe
template. Diagnose the environment at any time:

```bash
./.venv/bin/python shorts.py doctor
./.venv/bin/python shorts.py doctor --json
```

## Connect Gemini

Create a key in [Google AI Studio](https://aistudio.google.com/apikey), then add
it locally:

```env
# pipeline/.env
GEMINI_API_KEY=your_key
ELEVENLABS_API_KEY=your_optional_voice_key
```

The default `pipeline/production.json` uses the stable
`gemini-3.1-flash-image` model through Google's v1 API:

```json
"image_provider": "gemini",
"image_model": "gemini-3.1-flash-image",
"image_size": "1K"
```

For Vertex AI, set `image_provider` to `vertex`, authenticate `gcloud`, and add
`GOOGLE_CLOUD_PROJECT` plus optional `GOOGLE_CLOUD_ACCOUNT` to `pipeline/.env`.
The code obtains short-lived access tokens and never writes them to tracked
files.

## Add references

Place your owned identity/style frames under `references/` and list them in
`pipeline/production.json`:

```json
"reference_images": [
  "references/identity-sheet.png",
  "references/style-frame-1.png",
  "references/style-frame-2.png"
]
```

Reference images are ignored by Git. Optional owner-cleared finishing assets:

```text
assets/music/track.mp3
assets/channel/avatar.png
assets/channel/endcard_voice.mp3
```

## Produce one Short

```bash
./.venv/bin/python shorts.py init \
  --topic "Your verified story" \
  --slug ep001-your-story \
  --scenes 16
```

Ask your AI coding agent to read `AGENTS.md` and replace all placeholders in
`episodes/ep001-your-story/bits.json` and `episode.json`. Then run:

```bash
./.venv/bin/python shorts.py validate --slug ep001-your-story
./.venv/bin/python shorts.py board --slug ep001-your-story
```

Review `storyboard/contact-sheet.png`. The owner—not the agent—then explicitly
approves it:

```bash
./.venv/bin/python shorts.py approve --slug ep001-your-story
./.venv/bin/python shorts.py gen --slug ep001-your-story
./.venv/bin/python shorts.py install --slug ep001-your-story
./.venv/bin/python shorts.py render --slug ep001-your-story
./.venv/bin/python shorts.py qa --slug ep001-your-story
```

`qa` performs a full decode, resolution/audio/caption checks, black-frame and
freeze detection, audio-level and long-silence checks, and creates
`qa/midpoints-contact-sheet.jpg`. A passing report is required for release.

## Prepare and approve a release

```bash
./.venv/bin/python shorts.py release \
  --slug ep001-your-story \
  --slot "2026-07-20 17:30" \
  --timezone "Asia/Almaty"
```

Review `publish-package.md`: title, description, tags, final hash, QA result,
audience and target slot. Upload remains blocked until a separate explicit
approval names the allowed visibility:

```bash
./.venv/bin/python shorts.py approve-release \
  --slug ep001-your-story \
  --privacy private
```

Only after that gate, an owner who configured YouTube OAuth may run:

```bash
./.venv/bin/pip install -r pipeline/requirements-youtube.txt
./.venv/bin/python pipeline/upload.py \
  --episode episodes/ep001-your-story \
  --privacy private
```

The uploader reads the reviewed publish package, checks all hashes, verifies
the actual YouTube title/privacy after upload and writes `release-status.json`.
Changing the final, QA report, package or requested privacy invalidates approval.

## Batch manifest

After several Shorts pass QA, create one queue manifest without publishing:

```bash
./.venv/bin/python shorts.py batch \
  --slugs ep001-one,ep002-two,ep003-three \
  --slots "2026-07-20 17:30,2026-07-21 01:30,2026-07-21 09:30" \
  --output releases/2026-07-20.json
```

## Recovery and status

```bash
./.venv/bin/python shorts.py status --slug ep001-your-story --json
./.venv/bin/python shorts.py gen --slug ep001-your-story --only 7,13
./.venv/bin/python shorts.py board --slug ep001-your-story --force
./.venv/bin/python shorts.py render --slug ep001-your-story --force
```

Approvals bind the storyboard, beat plan, narration, render config and
references. The final build manifest additionally binds generated images,
installed scenes, voice, timestamps, render props and final MP4. Any later
change produces a stale status and requires the appropriate step again.

## Optional providers

Install the advanced AI/video adapters only when needed:

```bash
./.venv/bin/pip install -r pipeline/requirements-ai.txt
```

- `--provider gemini`: Gemini Developer API and `GEMINI_API_KEY`.
- `--provider vertex`: Google image generation through Vertex/gcloud.
- `--provider fal`: Nano Banana through FAL and `FAL_KEY`.
- `build_bits2.py ... animate --provider veo|fal|ws`: optional scene video.

Animation commands retain explicit cost caps. Static scenes with deterministic
Remotion motion remain the safe default.

See `SECURITY.md`, `THIRD_PARTY.md`, `CONTRIBUTING.md`, and `AGENTS.md` before
production use.
