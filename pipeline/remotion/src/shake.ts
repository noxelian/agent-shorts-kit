import { hashInt } from "./prng";

// Impact micro-shake. Punchy: the view jolts for a couple of frames in a
// deterministic per-impact direction, alternating sign each frame so it reads as
// a sharp rattle. Smooth (`ease`): a single soft bump that starts at full
// amplitude on the cut and eases to zero over `frames` with no per-frame flip, so
// it lands rather than twitches.

export type Offset = { readonly x: number; readonly y: number };

export const ZERO_OFFSET: Offset = { x: 0, y: 0 };

export const shakeOffset = (
  frame: number,
  impactFrames: readonly number[],
  amplitudePx: number,
  frames: number,
  ease: boolean,
): Offset => {
  for (let i = 0; i < impactFrames.length; i += 1) {
    const start = impactFrames[i];
    const age = frame - start;
    if (age >= 0 && age < frames) {
      const angle = (hashInt(Math.round(start), 91) / 4294967296) * Math.PI * 2;
      const progress = age / frames;
      // Eased bump: quadratic ease-out settle, single direction. Rattle: linear
      // decay with an every-frame sign flip.
      const magnitude = ease
        ? amplitudePx * (1 - progress) * (1 - progress)
        : amplitudePx * (1 - progress) * (age % 2 === 0 ? 1 : -1);
      return { x: Math.cos(angle) * magnitude, y: Math.sin(angle) * magnitude };
    }
  }
  return ZERO_OFFSET;
};
