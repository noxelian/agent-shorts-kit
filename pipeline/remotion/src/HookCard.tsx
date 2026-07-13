import { AbsoluteFill, interpolate, useCurrentFrame } from "remotion";
import type { HookConfig } from "./types";

type HookCardProps = {
  readonly words: readonly string[];
  readonly motion: HookConfig;
};

const CLAMP = { extrapolateLeft: "clamp", extrapolateRight: "clamp" } as const;

// Cold-open title card: 2-4 hook words slammed on screen in the first frames and
// gone by ~1.3s, so a swiping viewer reads the promise before the story starts.
export const HookCard: React.FC<HookCardProps> = ({ words, motion }) => {
  const frame = useCurrentFrame();
  if (!motion.enable || words.length === 0) {
    return null;
  }
  if (frame < motion.cardInFrame || frame > motion.cardOutFrame) {
    return null;
  }

  const age = frame - motion.cardInFrame;
  const inLen = motion.cardHoldFrame - motion.cardInFrame;
  const scaleIn = interpolate(age, [0, inLen * 0.6, inLen], [0.55, 1.08, 1], CLAMP);
  const fadeStart = motion.cardOutFrame - 6;
  const opacity = interpolate(frame, [motion.cardInFrame, motion.cardInFrame + 3], [0, 1], CLAMP);
  const outOpacity = interpolate(frame, [fadeStart, motion.cardOutFrame], [1, 0], CLAMP);
  const scaleOut = interpolate(frame, [fadeStart, motion.cardOutFrame], [1, 1.12], CLAMP);
  const scale = scaleIn * scaleOut;

  const accent = words.length - 1;

  return (
    <AbsoluteFill
      style={{
        justifyContent: "center",
        alignItems: "center",
        paddingLeft: 70,
        paddingRight: 70,
      }}
    >
      <div
        style={{
          display: "flex",
          flexWrap: "wrap",
          justifyContent: "center",
          gap: "0 26px",
          fontFamily: "Arial Black, Arial, sans-serif",
          fontWeight: 900,
          fontSize: motion.cardFontPx,
          lineHeight: 1.02,
          textAlign: "center",
          textTransform: "uppercase",
          opacity: Math.min(opacity, outOpacity),
          transform: `scale(${scale}) rotate(-3deg)`,
        }}
      >
        {words.map((word, index) => (
          <span
            key={`${word}-${index}`}
            style={{
              color: index === accent ? "#ffe14d" : "#ffffff",
              WebkitTextStroke: "14px #000000",
              paintOrder: "stroke fill",
              textShadow: "0 10px 0 #000000, 0 0 26px rgba(0,0,0,0.7)",
              display: "inline-block",
            }}
          >
            {word}
          </span>
        ))}
      </div>
    </AbsoluteFill>
  );
};
