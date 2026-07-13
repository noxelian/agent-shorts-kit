import type { Word } from "./types";

// Deterministic mouth-flap / blink / body-language timing. Every value below is
// derived purely from the current frame and the word timings so Remotion renders
// identically on every pass (no Math.random / Date.now allowed).

export type Interval = {
  readonly start: number;
  readonly end: number;
};

export type FrameKey = "closed" | "half" | "open" | "blink";

// Treat words closer than this as one continuous utterance so the mouth does
// not snap shut between every syllable.
export const MERGE_GAP_SECONDS = 0.25;
// Mouth flap frequency while speaking (steps advance at ~2x this rate so the
// closed -> half -> open -> half cycle reads as a smooth flap).
export const FLAP_HZ = 7;
// Idle blink cadence, offset so it never lands on the scene cuts.
export const BLINK_PERIOD_SECONDS = 3.5;
export const BLINK_DURATION_SECONDS = 0.15;
export const BLINK_OFFSET_SECONDS = 1.3;

// Collapse the word timings into speech intervals, merging gaps below the
// threshold. Built immutably via reduce so there is no in-place mutation.
export const mergeIntervals = (
  words: readonly Word[],
  gapSeconds: number,
): readonly Interval[] =>
  words.reduce<readonly Interval[]>((acc, word) => {
    const last = acc[acc.length - 1];
    if (last !== undefined && word.start - last.end < gapSeconds) {
      const merged: Interval = {
        start: last.start,
        end: Math.max(last.end, word.end),
      };
      return [...acc.slice(0, -1), merged];
    }
    return [...acc, { start: word.start, end: word.end }];
  }, []);

export const isSpeaking = (intervals: readonly Interval[], t: number): boolean =>
  intervals.some((interval) => t >= interval.start && t < interval.end);

// Start time (seconds) of the speech interval containing t, else null. Used to
// phase the talking body sway from the top of each utterance.
export const speechPhaseStart = (
  intervals: readonly Interval[],
  t: number,
): number | null => {
  for (const interval of intervals) {
    if (t >= interval.start && t < interval.end) {
      return interval.start;
    }
  }
  return null;
};

// Which sprite to show this frame. Falls back gracefully whenever the optional
// half / open / blink frames are absent, preserving the original behaviour.
export const activeFrameKey = (params: {
  readonly speaking: boolean;
  readonly hasHalf: boolean;
  readonly hasOpen: boolean;
  readonly hasBlink: boolean;
  readonly frame: number;
  readonly fps: number;
  readonly flapHz: number;
  readonly t: number;
}): FrameKey => {
  const { speaking, hasHalf, hasOpen, hasBlink, frame, fps, flapHz, t } = params;

  if (speaking && hasOpen) {
    const framesPerStep = Math.max(1, Math.round(fps / (flapHz * 2)));
    const step = Math.floor(frame / framesPerStep) % 4;
    const cycle: readonly FrameKey[] = [
      "closed",
      hasHalf ? "half" : "closed",
      "open",
      hasHalf ? "half" : "open",
    ];
    return cycle[step];
  }

  if (!speaking && hasBlink) {
    const phase = (t + BLINK_OFFSET_SECONDS) % BLINK_PERIOD_SECONDS;
    if (phase < BLINK_DURATION_SECONDS) {
      return "blink";
    }
  }

  return "closed";
};

// Squash-stretch envelope for the per-word bounce: a fast attack to 1 then a
// slower decay to 0, retriggered on every word start near the current frame.
export const bounceEnvelope = (
  frame: number,
  wordStartFrames: readonly number[],
  attack: number,
  decay: number,
): number => {
  let best = 0;
  for (let i = 0; i < wordStartFrames.length; i += 1) {
    const age = frame - wordStartFrames[i];
    if (age < 0 || age > attack + decay) {
      continue;
    }
    const value = age < attack ? age / attack : 1 - (age - attack) / decay;
    if (value > best) {
      best = value;
    }
  }
  return best;
};
