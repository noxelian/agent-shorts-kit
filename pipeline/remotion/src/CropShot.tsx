import { AbsoluteFill, Easing, Img, interpolate, staticFile, useCurrentFrame } from "remotion";
import type { Shot } from "./shots";
import type { ShotsConfig } from "./types";

type CropShotProps = {
  readonly src: string;
  readonly shot: Shot;
  readonly config: ShotsConfig;
  readonly headStart: number;
};

const CLAMP = { extrapolateLeft: "clamp", extrapolateRight: "clamp" } as const;
const EASE_IN_OUT = { ...CLAMP, easing: Easing.inOut(Easing.cubic) } as const;

// Largest drift (in %) that still keeps the zoomed image covering the frame, so
// a lateral move never exposes a black edge. Headroom is (zoom-1)/2 on each side.
const safeDriftPct = (zoom: number, wanted: number): number => {
  const headroomPct = ((zoom - 1) / 2) * 100 * 0.8;
  return Math.max(0, Math.min(wanted, headroomPct));
};

// Renders one shot: a zoomed crop of the scene image that pushes in, pulls out,
// or drifts laterally over its own length. imageRendering:pixelated keeps the
// pixel grid hard and chunky (on-brand) even at the detail zoom rather than mushy.
export const CropShot: React.FC<CropShotProps> = ({ src, shot, config, headStart }) => {
  const frame = useCurrentFrame() + headStart;
  // easeInOut so a push/pull/lateral has no velocity discontinuity at either cut;
  // the head-start still opens the first shot mid-move so t=0 already has motion.
  const progress = interpolate(frame, [0, shot.len], [0, 1], config.ease ? EASE_IN_OUT : CLAMP);

  const grow = shot.zoom * config.pushPct;
  let scale = shot.zoom;
  if (shot.move === "push") {
    scale = shot.zoom + grow * progress;
  } else if (shot.move === "pull") {
    scale = shot.zoom + grow * (1 - progress);
  }
  scale = Math.min(config.maxZoom + grow, scale);

  const drift = safeDriftPct(scale, config.driftPct);
  const lateral = shot.move === "lateral";
  const translateX = lateral ? interpolate(progress, [0, 1], [-drift, drift]) * shot.moveSign : 0;
  // A whisper of vertical drift on the zoom moves so a push/pull is never dead still.
  const translateY = lateral ? 0 : interpolate(progress, [0, 1], [drift * 0.4, -drift * 0.4]) * shot.moveSign;

  return (
    <AbsoluteFill>
      <Img
        src={staticFile(src)}
        style={{
          width: "100%",
          height: "100%",
          objectFit: "cover",
          transformOrigin: `${shot.focusX * 100}% ${shot.focusY * 100}%`,
          transform: `translate(${translateX}%, ${translateY}%) scale(${scale})`,
          imageRendering: "pixelated",
        }}
      />
    </AbsoluteFill>
  );
};
