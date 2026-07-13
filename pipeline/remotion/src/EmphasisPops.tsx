import { AbsoluteFill, Easing, interpolate, Sequence, useCurrentFrame, useVideoConfig } from "remotion";
import type { EmphasisConfig, EmphasisPop } from "./types";

type EmphasisPopsProps = {
  readonly pops: readonly EmphasisPop[];
  readonly motion: EmphasisConfig;
};

const CLAMP = { extrapolateLeft: "clamp", extrapolateRight: "clamp" } as const;
const EASE_OUT = { ...CLAMP, easing: Easing.out(Easing.cubic) } as const;

type OnePopProps = {
  readonly word: string;
  readonly motion: EmphasisConfig;
  readonly total: number;
};

// One keyword slam in the upper-middle zone. Punchy: scale-in overshoot -> hold
// -> fade + slight grow, with a hard 1-frame white flash on the hit. Smooth: a
// soft easeOut scale-in over riseFrames -> hold -> fade while drifting up over
// fallFrames, with the flash reduced to a barely-there 4% over a few frames.
const OnePop: React.FC<OnePopProps> = ({ word, motion, total }) => {
  const frame = useCurrentFrame();
  const { height } = useVideoConfig();

  const rise = motion.riseFrames;
  const holdEnd = motion.holdFrames;
  const fallEnd = holdEnd + motion.fallFrames;

  const scaleIn = motion.overshoot
    ? interpolate(frame, [0, rise * 0.6, rise], [0.45, 1.15, 1], CLAMP)
    : interpolate(frame, [0, rise], [0.7, 1], EASE_OUT);
  const opacityIn = interpolate(frame, [0, Math.max(1, rise * 0.4)], [0, 1], CLAMP);
  const opacityOut = interpolate(frame, [holdEnd, fallEnd], [1, 0], CLAMP);
  const exitScale = motion.overshoot ? interpolate(frame, [holdEnd, fallEnd], [1, 1.08], CLAMP) : 1;
  const driftY = interpolate(frame, [holdEnd, fallEnd], [0, -motion.driftUpPx], EASE_OUT);
  const flash =
    motion.flashOpacity > 0
      ? interpolate(frame, [0, motion.flashFrames], [motion.flashOpacity, 0], CLAMP)
      : 0;

  return (
    <AbsoluteFill>
      <AbsoluteFill
        style={{ backgroundColor: "#ffffff", opacity: flash, mixBlendMode: "screen" }}
      />
      <AbsoluteFill
        style={{
          justifyContent: "flex-start",
          alignItems: "center",
        }}
      >
        <div
          style={{
            marginTop: (motion.yPct / 100) * height,
            fontFamily: "Arial Black, Arial, sans-serif",
            fontWeight: 900,
            fontSize: motion.fontSizePx,
            color: motion.color,
            textTransform: "uppercase",
            WebkitTextStroke: `${motion.outlinePx}px ${motion.outlineColor}`,
            paintOrder: "stroke fill",
            textShadow: `0 8px 0 ${motion.outlineColor}, 0 0 22px rgba(0,0,0,0.7)`,
            opacity: Math.min(opacityIn, opacityOut) * (total > 0 ? 1 : 0),
            transform: `translateY(${driftY}px) scale(${scaleIn * exitScale}) rotate(-2deg)`,
          }}
        >
          {word}
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

// Sparse word-timed keyword pops, distinct from the bottom karaoke captions.
export const EmphasisPops: React.FC<EmphasisPopsProps> = ({ pops, motion }) => {
  const { fps } = useVideoConfig();
  if (!motion.enable || pops.length === 0) {
    return null;
  }
  const life = motion.holdFrames + motion.fallFrames + 1;
  return (
    <>
      {pops.map((pop, index) => (
        <Sequence
          key={`${pop.word}-${index}`}
          from={Math.max(0, Math.round(pop.start * fps))}
          durationInFrames={life}
        >
          <OnePop word={pop.word} motion={motion} total={pops.length} />
        </Sequence>
      ))}
    </>
  );
};
