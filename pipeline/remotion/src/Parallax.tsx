import { AbsoluteFill, Easing, Img, interpolate, staticFile, useCurrentFrame } from "remotion";
import type { ParallaxConfig, SceneLayer } from "./types";

type Vector = { readonly x: number; readonly y: number };

// Per-scene drift direction. Consecutive scenes push opposite ways so the eye
// keeps noticing the parallax instead of habituating to one direction.
const DIRECTIONS: readonly Vector[] = [
  { x: 1, y: 0.35 },
  { x: -1, y: -0.25 },
  { x: 0.5, y: 1 },
  { x: -0.6, y: -1 },
  { x: 1, y: -0.5 },
];

const normalize = ({ x, y }: Vector): Vector => {
  const length = Math.hypot(x, y) || 1;
  return { x: x / length, y: y / length };
};

const directionFor = (index: number): Vector =>
  normalize(DIRECTIONS[index % DIRECTIONS.length]);

type ParallaxProps = {
  readonly layer: SceneLayer;
  readonly index: number;
  readonly frames: number;
  readonly config: ParallaxConfig;
  readonly headStart?: number;
};

// Real parallax: the background plate scales up slightly and drifts slowly, while
// the foreground cutout drifts several times faster along the same vector plus a
// subtle slow zoom, so foreground objects visibly move against the backdrop.
export const Parallax: React.FC<ParallaxProps> = ({ layer, index, frames, config, headStart = 0 }) => {
  const frame = useCurrentFrame() + headStart;
  // easeInOut the drift so the parallax has no velocity jump at the scene cut.
  const progress = interpolate(frame, [0, frames], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    ...(config.ease ? { easing: Easing.inOut(Easing.cubic) } : {}),
  });
  const centered = progress - 0.5;
  const dir = directionFor(index);

  const bgX = dir.x * config.bgDriftPx * centered;
  const bgY = dir.y * config.bgDriftPx * centered;
  const fgDrift = config.bgDriftPx * config.fgDriftMultiplier;
  const fgX = dir.x * fgDrift * centered;
  const fgY = dir.y * fgDrift * centered;
  // The foreground shares the background's base scale so the cutout aligns with
  // the plate at rest (no halo); its slow zoom rides on top. translate is applied
  // before scale so the drift stays in screen pixels.
  const fgScale = config.bgScale * (1 + (config.fgZoomPct / 100) * progress);

  return (
    <AbsoluteFill>
      <Img
        src={staticFile(layer.bg)}
        style={{
          width: "100%",
          height: "100%",
          objectFit: "cover",
          transform: `translate(${bgX}px, ${bgY}px) scale(${config.bgScale})`,
          imageRendering: "pixelated",
        }}
      />
      <Img
        src={staticFile(layer.fg)}
        style={{
          position: "absolute",
          inset: 0,
          width: "100%",
          height: "100%",
          objectFit: "cover",
          transform: `translate(${fgX}px, ${fgY}px) scale(${fgScale})`,
          imageRendering: "pixelated",
        }}
      />
    </AbsoluteFill>
  );
};
