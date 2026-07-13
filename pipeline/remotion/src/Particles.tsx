import { AbsoluteFill, useCurrentFrame, useVideoConfig } from "remotion";
import { rand01n } from "./prng";

type ParticlesProps = {
  readonly index: number;
  readonly count: number;
  readonly sizePx: number;
  readonly tint: string;
};

// Chunky dust / ember motes drifting on seeded sinusoidal paths. Direction of the
// slow vertical drift alternates per scene (embers rise on odd scenes, dust
// settles on even ones). Everything is a pure function of the frame + seeds.
export const Particles: React.FC<ParticlesProps> = ({ index, count, sizePx, tint }) => {
  const frame = useCurrentFrame();
  const { width, height } = useVideoConfig();
  const rise = index % 2 === 1 ? -1 : 1;
  const span = height + sizePx * 2;

  return (
    <AbsoluteFill style={{ pointerEvents: "none", overflow: "hidden" }}>
      {Array.from({ length: count }, (_unused, i) => {
        const baseX = rand01n(index, i, 1) * width;
        const baseY = rand01n(index, i, 2) * span;
        const speed = 0.25 + rand01n(index, i, 4) * 0.6;
        const swayAmp = 14 + rand01n(index, i, 5) * 40;
        const phase = rand01n(index, i, 6) * Math.PI * 2;
        const size = sizePx + Math.floor(rand01n(index, i, 7) * 3);

        const drifted = baseY + rise * speed * frame;
        const y = ((drifted % span) + span) % span - sizePx;
        const x = baseX + Math.sin(frame * 0.02 * speed + phase) * swayAmp;
        const opacity =
          0.18 + 0.32 * (0.5 + 0.5 * Math.sin(frame * 0.03 + phase));

        return (
          <div
            key={i}
            style={{
              position: "absolute",
              left: x,
              top: y,
              width: size,
              height: size,
              backgroundColor: tint,
              opacity,
              boxShadow: `0 0 ${size * 2}px ${tint}`,
              imageRendering: "pixelated",
            }}
          />
        );
      })}
    </AbsoluteFill>
  );
};
