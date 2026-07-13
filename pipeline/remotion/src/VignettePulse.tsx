import { AbsoluteFill, useCurrentFrame } from "remotion";

type VignettePulseProps = {
  readonly index: number;
  readonly strength: number;
  readonly tempSwayPct: number;
};

// A slow vignette breath plus a very subtle colour-temperature sway (warm <-> cool
// by +/- tempSwayPct). Kept low-contrast so it never distracts from the scene.
export const VignettePulse: React.FC<VignettePulseProps> = ({ index, strength, tempSwayPct }) => {
  const frame = useCurrentFrame();
  const phase = index * 1.3;
  const pulse = strength * (0.82 + 0.18 * (0.5 + 0.5 * Math.sin(frame * 0.03 + phase)));
  const temp = Math.sin(frame * 0.015 + phase) * (tempSwayPct / 100);
  const warm = temp >= 0;
  const tempColor = warm
    ? `rgba(255, 176, 96, ${temp * 0.6})`
    : `rgba(96, 168, 255, ${-temp * 0.6})`;

  return (
    <AbsoluteFill style={{ pointerEvents: "none" }}>
      <AbsoluteFill
        style={{
          background: `radial-gradient(ellipse at center, rgba(0,0,0,0) 52%, rgba(0,0,0,${pulse}) 100%)`,
        }}
      />
      <AbsoluteFill style={{ backgroundColor: tempColor, mixBlendMode: "soft-light" }} />
    </AbsoluteFill>
  );
};
