import { Easing, interpolate } from "remotion";
import type { HookConfig } from "./types";

const CLAMP = { extrapolateLeft: "clamp", extrapolateRight: "clamp" } as const;
const EASE_OUT = { ...CLAMP, easing: Easing.out(Easing.cubic) } as const;
const EASE_IN_OUT = { ...CLAMP, easing: Easing.inOut(Easing.cubic) } as const;

// Snap punch-in for the first-1.5s hook. Punchy: 1.0 -> punchScale over ~2 frames
// (a hard step) then back over ~10. Smooth (`punchSpring`): an easeOut ramp over
// ~7 frames then an easeInOut settle over ~11, so it still reads as a camera
// punch but never teleports, and leaves no residual zoom behind.
export const hookPunchScale = (frame: number, cfg: HookConfig): number => {
  if (!cfg.enable) {
    return 1;
  }
  const age = frame - cfg.punchFrame;
  const up = cfg.punchRiseFrames;
  const back = cfg.punchBackFrames;
  if (age < 0 || age > up + back) {
    return 1;
  }
  if (age <= up) {
    return interpolate(age, [0, up], [1, cfg.punchScale], cfg.punchSpring ? EASE_OUT : CLAMP);
  }
  return interpolate(
    age,
    [up, up + back],
    [cfg.punchScale, 1],
    cfg.punchSpring ? EASE_IN_OUT : CLAMP,
  );
};

// Head-start (in frames) for the very first shot so the video opens mid-move
// with non-zero velocity at frame 0 instead of a dead slow-zoom.
export const headStartFrames = (shotLen: number, cfg: HookConfig): number =>
  cfg.enable ? Math.round(shotLen * cfg.headStartFrac) : 0;
