import { rand01, rand01n } from "./prng";
import type { ShotsConfig } from "./types";

// A scene is split into 2-3 hard-cut shots of the SAME image so the framing
// changes every few seconds: wide establishing -> detail punch-in -> alternate
// crop. Every value here is derived from the scene index via the seeded prng so
// the plan is identical on every render pass (Remotion forbids Math.random).

export type ShotType = "wide" | "detail" | "alt";
export type ShotMove = "push" | "pull" | "lateral";

export type Shot = {
  readonly type: ShotType;
  readonly from: number; // frame offset within the scene clip
  readonly len: number;
  readonly zoom: number;
  readonly focusX: number;
  readonly focusY: number;
  readonly move: ShotMove;
  readonly moveSign: number;
};

type Focus = { readonly x: number; readonly y: number };

// Detail crop regions: upper-third, left, right. Varied per shot so no two
// detail punches frame the same part of the image.
const FOCI: readonly Focus[] = [
  { x: 0.5, y: 0.3 },
  { x: 0.33, y: 0.5 },
  { x: 0.67, y: 0.5 },
];

const MOVES: readonly ShotMove[] = ["push", "pull", "lateral"];
const TYPES: readonly ShotType[] = ["wide", "detail", "alt"];

// Cut cadence: aim for one cut every (min+max)/2 seconds, clamped to 2-3 shots.
export const shotCountFor = (frames: number, fps: number, cfg: ShotsConfig): number => {
  const seconds = frames / Math.max(1, fps);
  const target = (cfg.minSeconds + cfg.maxSeconds) / 2;
  return Math.max(2, Math.min(3, Math.round(seconds / Math.max(1, target))));
};

// Split `frames` into `count` shot lengths with a small deterministic jitter,
// guaranteeing the parts sum back to exactly `frames` (duration never drifts).
const splitFrames = (seed: number, frames: number, count: number): readonly number[] => {
  const weights = Array.from(
    { length: count },
    (_unused, i) => 0.85 + 0.3 * rand01(seed * 17 + i + 1, 53),
  );
  const total = weights.reduce((acc, w) => acc + w, 0);
  const floored = weights.map((w) => Math.max(1, Math.floor((w / total) * frames)));
  const used = floored.reduce((acc, w) => acc + w, 0);
  const remainder = frames - used;
  return floored.map((len, i) => (i === count - 1 ? Math.max(1, len + remainder) : len));
};

const clampZoom = (zoom: number, cfg: ShotsConfig): number =>
  Math.min(cfg.maxZoom, Math.max(1, zoom));

const zoomForType = (type: ShotType, seed: number, cfg: ShotsConfig): number => {
  if (type === "detail") {
    return clampZoom(
      cfg.detailZoomMin + (cfg.detailZoomMax - cfg.detailZoomMin) * rand01(seed, 211),
      cfg,
    );
  }
  if (type === "alt") {
    return clampZoom(
      cfg.altZoomMin + (cfg.altZoomMax - cfg.altZoomMin) * rand01(seed, 307),
      cfg,
    );
  }
  return clampZoom(cfg.wideZoom, cfg);
};

const focusForType = (type: ShotType, sceneIndex: number, shotIndex: number): Focus => {
  if (type === "wide") {
    return { x: 0.5, y: 0.5 };
  }
  const detail = FOCI[(sceneIndex + shotIndex) % FOCI.length];
  if (type === "detail") {
    return detail;
  }
  // alt-crop frames the opposite offset (mirror around the centre).
  return { x: 1 - detail.x, y: 1 - detail.y };
};

// Deterministic shot plan for one scene. Shot 0 is always the wide establishing
// shot (carries the between-scene transition); later shots hard-cut in.
export const planShots = (
  sceneIndex: number,
  frames: number,
  fps: number,
  cfg: ShotsConfig,
): readonly Shot[] => {
  if (!cfg.enable) {
    return [
      {
        type: "wide",
        from: 0,
        len: frames,
        zoom: clampZoom(cfg.wideZoom, cfg),
        focusX: 0.5,
        focusY: 0.5,
        move: MOVES[sceneIndex % MOVES.length],
        moveSign: sceneIndex % 2 === 0 ? 1 : -1,
      },
    ];
  }

  const count = shotCountFor(frames, fps, cfg);
  const lens = splitFrames(sceneIndex, frames, count);
  const baseSign = sceneIndex % 2 === 0 ? 1 : -1;
  const moveStart = sceneIndex % MOVES.length;

  return lens.reduce<readonly Shot[]>((acc, len, shotIndex) => {
    const from = acc.reduce((sum, shot) => sum + shot.len, 0);
    const type = TYPES[Math.min(shotIndex, TYPES.length - 1)];
    const focus = focusForType(type, sceneIndex, shotIndex);
    // Stepping by 1 through the 3-move cycle guarantees no move repeats back to
    // back; the sign alternates so a detail push and the following alt-crop drift
    // in opposite directions.
    const move = MOVES[(moveStart + shotIndex) % MOVES.length];
    const moveSign = baseSign * (shotIndex % 2 === 0 ? 1 : -1);
    const seed = sceneIndex * 131 + shotIndex * 7 + Math.round(rand01n(sceneIndex, shotIndex, 5) * 3);
    const shot: Shot = {
      type,
      from,
      len,
      zoom: zoomForType(type, seed, cfg),
      focusX: focus.x,
      focusY: focus.y,
      move,
      moveSign,
    };
    return [...acc, shot];
  }, []);
};
