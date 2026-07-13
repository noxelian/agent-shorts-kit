import { rand01 } from "./prng";
import type { TransitionsConfig } from "./types";

// Three pixel-native scene transitions, rotated deterministically by the scene
// boundary index. The dissolve and wipe are expressed as CSS mask images (an
// inline SVG of white cells) applied to the *incoming* scene, which sits on top
// of the outgoing scene and reveals cell-by-cell. The zoom-punch is a pure
// transform handled by the scene clip itself.

export type TransitionKind = "dissolve" | "wipe" | "punch";

export const KINDS: readonly TransitionKind[] = ["dissolve", "wipe", "punch"];

export const transitionKind = (boundaryIndex: number): TransitionKind => {
  const length = KINDS.length;
  return KINDS[((boundaryIndex % length) + length) % length];
};

// Per-kind window length in frames, clamped so it never exceeds the configured
// maximum overlap (cfg.frames). Punchy keeps the original tight windows
// (dissolve 0.4s, wipe 0.35s, punch 0.3s); smooth lengthens dissolve/wipe to
// ~16 frames (0.53s) and the zoom-punch to ~10 so the cross-fades breathe.
export const transitionLength = (
  kind: TransitionKind,
  fps: number,
  cfg: TransitionsConfig,
): number => {
  const seconds = cfg.smooth
    ? kind === "punch"
      ? 0.33
      : 0.53
    : kind === "dissolve"
      ? 0.4
      : kind === "wipe"
        ? 0.35
        : 0.3;
  return Math.max(2, Math.min(cfg.frames, Math.round(seconds * fps)));
};

const svgMaskUrl = (rects: string, width: number, height: number): string =>
  `url("data:image/svg+xml,${encodeURIComponent(
    `<svg xmlns='http://www.w3.org/2000/svg' width='${width}' height='${height}'>` +
      `<g fill='#fff'>${rects}</g></svg>`,
  )}")`;

// Coarse-grid noise reveal: each cell flips to visible once the transition
// progress passes its deterministic per-cell threshold.
export const dissolveMask = (
  progress: number,
  width: number,
  height: number,
  cell: number,
  seed: number,
): string => {
  const cols = Math.ceil(width / cell);
  const rows = Math.ceil(height / cell);
  const parts: string[] = [];
  for (let cy = 0; cy < rows; cy += 1) {
    for (let cx = 0; cx < cols; cx += 1) {
      const id = cy * cols + cx;
      if (rand01(id, seed) < progress) {
        parts.push(
          `<rect x='${cx * cell}' y='${cy * cell}' width='${cell}' height='${cell}'/>`,
        );
      }
    }
  }
  return svgMaskUrl(parts.join(""), width, height);
};

// Hard-edged column wipe with a +/-1 cell stair jitter per row. Direction flips
// with the seed parity so consecutive wipes do not all run the same way.
export const wipeMask = (
  progress: number,
  width: number,
  height: number,
  cell: number,
  seed: number,
): string => {
  const cols = Math.ceil(width / cell);
  const rows = Math.ceil(height / cell);
  const front = progress * (cols + 1);
  const reverse = seed % 2 === 1;
  const parts: string[] = [];
  for (let cy = 0; cy < rows; cy += 1) {
    const jitter = Math.floor(rand01(cy, seed) * 3) - 1;
    const revealed = Math.max(0, Math.min(cols, Math.round(front + jitter)));
    if (revealed > 0) {
      const spanWidth = revealed * cell;
      const x = reverse ? width - spanWidth : 0;
      parts.push(
        `<rect x='${x}' y='${cy * cell}' width='${spanWidth}' height='${cell}'/>`,
      );
    }
  }
  return svgMaskUrl(parts.join(""), width, height);
};
