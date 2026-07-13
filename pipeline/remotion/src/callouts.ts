import type { Callout, CalloutStyle, ResolvedCallout } from "./types";

// Single resolution point for story callouts, shared by the visual layer
// (StoryCallouts), the SFX layer (impact on each event beat) and the music duck.
// Deriving the adjusted frames + per-style timing here once keeps the audio hits,
// the music duck and the on-screen band perfectly aligned.

// Per-style timing in SECONDS: scale/slide-IN, HOLD, fade-OUT. scoreboard/shock
// slam in fast, hold ~2.2s; label eases in and lingers ~2.5s.
type Timing = { readonly in: number; readonly hold: number; readonly out: number };

const TIMING: Record<CalloutStyle, Timing> = {
  scoreboard: { in: 0.27, hold: 2.2, out: 0.33 },
  shock: { in: 0.27, hold: 2.2, out: 0.33 },
  label: { in: 0.33, hold: 2.5, out: 0.27 },
};

// Minimum breathing room (seconds) between one callout clearing and the next
// landing, so a delayed callout never butts straight up against its predecessor.
const GAP_SECONDS = 0.1;

// Beats that fire a duck -> impact (the event markers). A "label" is a quiet tag,
// so it does not punch the audio.
export const isBeatStyle = (style: CalloutStyle): boolean => style !== "label";

// Resolve raw callouts (already {frame, text, style}) into render-ready callouts:
// bake per-style frame timing, sort by frame, and push any callout that would
// overlap the previous one later by at least GAP_SECONDS. Pure + deterministic.
export const resolveCallouts = (
  callouts: readonly Callout[],
  fps: number,
): readonly ResolvedCallout[] => {
  const gap = Math.round(GAP_SECONDS * fps);
  const sorted = [...callouts].sort((a, b) => a.frame - b.frame);
  const resolved: ResolvedCallout[] = [];
  let previousEnd = Number.NEGATIVE_INFINITY;
  for (const callout of sorted) {
    const timing = TIMING[callout.style] ?? TIMING.scoreboard;
    const inFrames = Math.round(timing.in * fps);
    const holdFrames = Math.round(timing.hold * fps);
    const outFrames = Math.round(timing.out * fps);
    const life = inFrames + holdFrames + outFrames;
    const frame = Math.max(callout.frame, previousEnd + gap);
    resolved.push({ ...callout, frame, inFrames, holdFrames, outFrames, life });
    previousEnd = frame + life;
  }
  return resolved;
};

// The event-beat frames (scoreboard/shock) after resolution, de-duped against the
// punchline beat (a callout within 1s of it is already covered by that impact).
export const calloutBeatFrames = (
  resolved: readonly ResolvedCallout[],
  punchlineFrame: number,
  fps: number,
): readonly number[] =>
  resolved
    .filter((callout) => isBeatStyle(callout.style))
    .map((callout) => callout.frame)
    .filter((frame) => punchlineFrame < 0 || Math.abs(frame - punchlineFrame) > fps);
