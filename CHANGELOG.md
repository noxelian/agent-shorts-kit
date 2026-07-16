# Changelog

## v0.2.0 — 2026-07-16

- Added schema-backed preflight validation that blocks placeholders, narration
  drift and scene-count mismatches before paid generation.
- Expanded storyboard approval to bind the episode, beat plan, render config
  and reference images.
- Added sealed build manifests for generated images, installed scenes, voice,
  timestamps, render props and final MP4.
- Added automated MP4 QA with decode, stream, black/freeze, audio, caption and
  midpoint-contact-sheet checks.
- Added reviewed release packages, explicit privacy-specific release approval,
  batch queue manifests and verified YouTube metadata/status capture.
- Updated the Gemini image request to the stable v1 response format and added
  configurable image size.
- Added one-command setup, actionable doctor output and GitHub Actions CI.

## v0.1.0 — 2026-07-13

- First public packaging of the production storyboard → scenes → TTS →
  Remotion workflow with a human storyboard approval gate.
