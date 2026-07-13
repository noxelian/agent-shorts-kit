# Agent Shorts Kit — production pipeline

The reproducible pipeline used to produce illustrated vertical Shorts:

```text
research + script
      ↓
episode.json + 16-beat bits.json
      ↓
one Gemini storyboard contact sheet
      ↓
explicit human approval bound to SHA-256
      ↓
Gemini 3.1 Flash Image scenes with identity/style/location references
      ↓
pixel-locked 1080×1920 scene install
      ↓
ElevenLabs/Edge TTS + word timestamps
      ↓
Remotion: narration-synced cuts, burned captions, SFX, motion, thumbnail
      ↓
out/final.mp4
```

No key, Google account, episode, unpublished media or OAuth token is included.

## Requirements

- Python 3.11+
- Node.js 20+
- FFmpeg and FFprobe
- Google Gemini API key, or a Google Cloud project with Vertex AI access
- optional ElevenLabs key for the production voice

## Install

```bash
git clone https://github.com/4ubak/agent-shorts-kit.git
cd agent-shorts-kit
python3 -m venv .venv
./.venv/bin/pip install -r pipeline/requirements-ai.txt
npm --prefix pipeline/remotion ci
cp .env.example pipeline/.env
```

## Connect Google Gemini

The simplest mode uses a key from [Google AI Studio](https://aistudio.google.com/apikey):

```env
# pipeline/.env
GEMINI_API_KEY=your_key
ELEVENLABS_API_KEY=your_optional_voice_key
```

Keep this default in `pipeline/production.json`:

```json
"image_provider": "gemini",
"image_model": "gemini-3.1-flash-image"
```

For Vertex AI credits instead, set `image_provider` to `vertex`, authenticate
`gcloud`, and configure:

```env
GOOGLE_CLOUD_PROJECT=your-project-id
GOOGLE_CLOUD_ACCOUNT=you@example.com
```

The code never stores access tokens; Vertex requests obtain a short-lived token
from `gcloud auth print-access-token`.

## Add identity and style references

Place your owned reference files under `references/` and list them in
`pipeline/production.json`:

```json
"reference_images": [
  "references/identity-sheet.png",
  "references/style-frame-1.png",
  "references/style-frame-2.png"
]
```

These files are ignored by git by default.

For the same finishing layers as the production setup, add owner-cleared assets:

```text
assets/music/track.mp3
assets/channel/avatar.png
assets/channel/endcard_voice.mp3
```

The renderer skips missing music/end-card media without failing. SFX are
synthesized deterministically by the pipeline.

## Produce one Short

Create the episode workspace:

```bash
./.venv/bin/python shorts.py init \
  --topic "Your verified story" \
  --slug ep001-your-story \
  --scenes 16
```

Ask your AI coding agent to read `AGENTS.md` and replace every placeholder in
`episodes/ep001-your-story/bits.json` and `episode.json`.

Generate one storyboard first:

```bash
./.venv/bin/python shorts.py board --slug ep001-your-story
```

Review `episodes/ep001-your-story/storyboard/contact-sheet.png`. Generation is
blocked until the owner explicitly approves:

```bash
./.venv/bin/python shorts.py approve --slug ep001-your-story
./.venv/bin/python shorts.py gen --slug ep001-your-story
./.venv/bin/python shorts.py install --slug ep001-your-story
./.venv/bin/python shorts.py render --slug ep001-your-story
```

The final file is `episodes/ep001-your-story/out/final.mp4`.

Useful recovery commands:

```bash
python shorts.py status --slug ep001-your-story --json
python shorts.py gen --slug ep001-your-story --only 7,13
python shorts.py board --slug ep001-your-story --force
python shorts.py render --slug ep001-your-story --force
```

Changing/replacing the storyboard invalidates approval. Regenerating selected
scenes remains resumable and does not spend credits on existing files.

## Optional providers

- `--provider gemini`: Gemini Developer API and `GEMINI_API_KEY`.
- `--provider vertex`: the same Google image family through Vertex/gcloud.
- `--provider fal`: Nano Banana 2 through FAL and `FAL_KEY`.
- `build_bits2.py ... animate --provider veo|fal|ws`: optional scene video.

Every animation command has an explicit cost cap. Static scenes with
deterministic Remotion motion are the safe default.

## Publishing safety

YouTube upload is a separate, owner-gated command. It is never invoked by
`shorts.py render`. Generated episodes, `.env`, OAuth credentials, tokens,
reference images, music and large media remain git-ignored.

See `SECURITY.md`, `THIRD_PARTY.md`, and `AGENTS.md` before production use.
