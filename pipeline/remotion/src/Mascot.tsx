import { AbsoluteFill, Img, spring, staticFile, useCurrentFrame, useVideoConfig } from "remotion";
import { useMemo } from "react";
import type { MascotFrames, MascotMotionConfig, Word } from "./types";
import {
  activeFrameKey,
  bounceEnvelope,
  isSpeaking,
  MERGE_GAP_SECONDS,
  mergeIntervals,
  speechPhaseStart,
} from "./mascotTiming";
import type { FrameKey } from "./mascotTiming";

type MascotProps = {
  readonly frames: MascotFrames;
  readonly sizePx: number;
  readonly words: readonly Word[];
  readonly motion: MascotMotionConfig;
};

type Layer = {
  readonly key: FrameKey;
  readonly src: string;
};

const BOUNCE_ATTACK = 2;
const BOUNCE_DECAY = 4;

// Narrator sprite in the bottom-left corner. It slides up with a single overshoot
// bounce on entrance, then keeps living: a mouth flap (closed/half/open) while
// narrating, a gentle lean sway phased to each utterance, a squash-stretch pop on
// every word, idle breathing, and an occasional blink. Every value is derived
// from useCurrentFrame so the render stays deterministic.
export const Mascot: React.FC<MascotProps> = ({ frames, sizePx, words, motion }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const t = frame / fps;

  const intervals = useMemo(() => mergeIntervals(words, MERGE_GAP_SECONDS), [words]);
  const wordStartFrames = useMemo(
    () => words.map((word) => Math.round(word.start * fps)),
    [words, fps],
  );
  const speaking = isSpeaking(intervals, t);

  const enter = spring({
    frame,
    fps,
    // Higher damping in smooth style -> a single soft overshoot, not a springy bounce.
    config: { damping: motion.entranceDamping, stiffness: 130, mass: 0.85 },
    durationInFrames: motion.entranceFrames,
  });
  const entranceY = (1 - enter) * (sizePx + 260);

  const bob = Math.sin(frame / 14) * 7;

  // Continuous talking body-sway phased to each utterance; swayHz sets the rate
  // (smooth ~0.5Hz, ±leanDeg). Idle drifts slower at a fraction of the amplitude.
  const swayOmega = 2 * Math.PI * motion.swayHz;
  const phaseStart = speechPhaseStart(intervals, t);
  const lean = speaking
    ? Math.sin((t - (phaseStart ?? 0)) * swayOmega) * motion.leanDeg
    : Math.sin(frame * 0.05) * motion.leanDeg * 0.35;

  const breath = 1 + (speaking ? 0 : Math.sin(frame * 0.1) * (motion.breathPct / 100));
  const bounce = bounceEnvelope(frame, wordStartFrames, BOUNCE_ATTACK, BOUNCE_DECAY);
  const squash = (motion.squashPct / 100) * bounce;
  const scaleX = breath * (1 + squash * 0.6);
  const scaleY = breath * (1 - squash);

  const activeKey = activeFrameKey({
    speaking,
    hasHalf: frames.half !== null,
    hasOpen: frames.open !== null,
    hasBlink: frames.blink !== null,
    frame,
    fps,
    flapHz: motion.flapHz,
    t,
  });

  // Stack every available frame and toggle opacity so swapping never triggers an
  // image reload / decode flash mid-flap.
  const layers: readonly Layer[] = [
    { key: "closed", src: frames.closed },
    ...(frames.half !== null ? [{ key: "half" as const, src: frames.half }] : []),
    ...(frames.open !== null ? [{ key: "open" as const, src: frames.open }] : []),
    ...(frames.blink !== null ? [{ key: "blink" as const, src: frames.blink }] : []),
  ];

  return (
    <AbsoluteFill style={{ justifyContent: "flex-end", alignItems: "flex-start" }}>
      <div
        style={{
          position: "relative",
          width: sizePx,
          height: sizePx,
          marginLeft: 36,
          marginBottom: 220,
          transform: `translateY(${entranceY + bob}px) rotate(${lean}deg) scale(${scaleX}, ${scaleY})`,
          transformOrigin: "50% 100%",
          filter: "drop-shadow(0 12px 10px rgba(0,0,0,0.55))",
        }}
      >
        {layers.map((layer) => (
          <Img
            key={layer.key}
            src={staticFile(layer.src)}
            style={{
              position: "absolute",
              inset: 0,
              width: sizePx,
              height: sizePx,
              objectFit: "contain",
              imageRendering: "pixelated",
              opacity: layer.key === activeKey ? 1 : 0,
            }}
          />
        ))}
      </div>
    </AbsoluteFill>
  );
};
