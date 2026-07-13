import { transitionKind, transitionLength } from "./transitions";
import type { MotionConfig } from "./types";

// Shared scene-window geometry so every consumer (Scenes render, shot-cut shake
// impacts, and the SFX layer) agrees byte-for-byte on where each scene starts,
// how long it runs, and where the between-scene transitions land. Deriving this
// in one place keeps the audio hits and the visual cuts perfectly aligned.

export type SceneWindow = {
  readonly index: number;
  readonly start: number; // nominal scene start (transition midpoint anchor)
  readonly from: number; // actual first frame of the clip (pulled back by the incoming transition)
  readonly duration: number;
};

const transitionFrames = (boundary: number, fps: number, motion: MotionConfig): number =>
  motion.transitions.enable
    ? transitionLength(transitionKind(boundary), fps, motion.transitions)
    : 0;

// Nominal scene-start frames. When sceneStarts (seconds, one per scene) maps the
// narration cleanly (right length, strictly increasing, in range) the scenes cut
// exactly where each line begins; otherwise it falls back to the equal split.
// Scene 0 always anchors to frame 0 regardless.
const startFrames = (
  count: number,
  durationInFrames: number,
  fps: number,
  sceneStarts: readonly number[] | null | undefined,
): readonly number[] => {
  if (sceneStarts && sceneStarts.length === count) {
    const frames = sceneStarts.map((seconds, index) =>
      index === 0 ? 0 : Math.round(seconds * fps),
    );
    const valid = frames.every(
      (frame, index) =>
        frame >= 0 &&
        frame < durationInFrames &&
        (index === 0 || frame > frames[index - 1]),
    );
    if (valid) {
      return frames;
    }
  }
  const per = Math.ceil(durationInFrames / count);
  return Array.from({ length: count }, (_unused, index) => index * per);
};

export const sceneWindows = (
  count: number,
  durationInFrames: number,
  fps: number,
  motion: MotionConfig,
  sceneStarts?: readonly number[] | null,
): readonly SceneWindow[] => {
  const safeCount = Math.max(count, 1);
  const starts = startFrames(safeCount, durationInFrames, fps, sceneStarts);
  return Array.from({ length: safeCount }, (_unused, index) => {
    const lenPrev = index > 0 ? transitionFrames(index - 1, fps, motion) : 0;
    const start = starts[index];
    const from = start - lenPrev;
    const end = index === safeCount - 1 ? durationInFrames : starts[index + 1];
    return { index, start, from, duration: end - from };
  });
};
