import { AbsoluteFill, useCurrentFrame, useVideoConfig } from "remotion";
import { rand01n } from "./prng";

type LightRaysProps = {
  readonly index: number;
  readonly count: number;
  readonly tint: string;
};

// A couple of soft diagonal god-rays that breathe slowly in opacity, composited
// with a screen blend so they lighten rather than wash out the scene.
export const LightRays: React.FC<LightRaysProps> = ({ index, count, tint }) => {
  const frame = useCurrentFrame();
  const { width, height } = useVideoConfig();
  const length = Math.hypot(width, height) * 1.4;

  return (
    <AbsoluteFill style={{ pointerEvents: "none", overflow: "hidden", mixBlendMode: "screen" }}>
      {Array.from({ length: count }, (_unused, i) => {
        const angle = -28 - i * 9 + rand01n(index, i, 1) * 6;
        const left = (width * (i + 1)) / (count + 1) + (rand01n(index, i, 2) - 0.5) * width * 0.2;
        const bandWidth = 90 + rand01n(index, i, 3) * 120;
        const phase = rand01n(index, i, 4) * Math.PI * 2;
        const breathe = 0.5 + 0.5 * Math.sin(frame * 0.018 + phase);
        const opacity = 0.05 + 0.16 * breathe;

        return (
          <div
            key={i}
            style={{
              position: "absolute",
              top: height / 2 - length / 2,
              left,
              width: bandWidth,
              height: length,
              background: `linear-gradient(to bottom, ${tint} 0%, rgba(255,255,255,0) 85%)`,
              transform: `rotate(${angle}deg)`,
              transformOrigin: "center",
              opacity,
              filter: "blur(6px)",
            }}
          />
        );
      })}
    </AbsoluteFill>
  );
};
