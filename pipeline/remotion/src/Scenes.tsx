import { AbsoluteFill, Sequence, useCurrentFrame, useVideoConfig } from "remotion";
import { useMemo } from "react";
import { hookPunchScale } from "./hook";
import { sceneWindows } from "./layout";
import { SceneClip } from "./SceneClip";
import type { Entrance, Exit } from "./SceneClip";
import { sentenceStartTimes } from "./sentences";
import { shakeOffset } from "./shake";
import { planShots } from "./shots";
import { transitionKind } from "./transitions";
import type { MotionConfig, SceneLayer, SceneVideo, Word } from "./types";

type ScenesProps = {
  readonly scenes: readonly string[];
  readonly layers: readonly (SceneLayer | null)[];
  readonly sceneVideos: readonly (SceneVideo | null)[];
  readonly sceneTints: readonly string[];
  readonly sceneEffects: readonly string[] | null;
  readonly sceneStarts: readonly number[] | null;
  readonly words: readonly Word[];
  readonly motion: MotionConfig;
  readonly durationInFrames: number;
};

const FALLBACK_TINT = "#c8a878";

// Orchestrates every scene: assigns each its base window (via the shared layout
// helper), splits it into hard-cut shots, overlaps neighbours by the transition
// length so the duration never changes, and applies the global impact
// micro-shake at scene starts, sentence starts AND every within-scene shot cut.
export const Scenes: React.FC<ScenesProps> = ({
  scenes,
  layers,
  sceneVideos,
  sceneTints,
  sceneEffects,
  sceneStarts,
  words,
  motion,
  durationInFrames,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const count = Math.max(scenes.length, 1);

  const windows = useMemo(
    () => sceneWindows(count, durationInFrames, fps, motion, sceneStarts),
    [count, durationInFrames, fps, motion, sceneStarts],
  );

  const shotsByScene = useMemo(
    () => windows.map((w) => planShots(w.index, w.duration, fps, motion.shots)),
    [windows, fps, motion.shots],
  );

  const impacts = useMemo(() => {
    const { onSceneStart, onShotCut, onSentenceStart } = motion.shake;
    const sceneStarts = onSceneStart ? windows.map((w) => w.start) : [];
    const shotCuts = onShotCut
      ? windows.flatMap((w, i) => shotsByScene[i].slice(1).map((shot) => w.from + shot.from))
      : [];
    const sentenceStarts = onSentenceStart
      ? sentenceStartTimes(words, motion.shake.sentenceGapSeconds).map((seconds) =>
          Math.round(seconds * fps),
        )
      : [];
    return [...sceneStarts, ...shotCuts, ...sentenceStarts];
  }, [windows, shotsByScene, words, motion.shake, fps]);

  const shake = motion.shake.enable
    ? shakeOffset(frame, impacts, motion.shake.px, motion.shake.frames, motion.shake.ease)
    : { x: 0, y: 0 };
  const punch = hookPunchScale(frame, motion.hook);

  return (
    <AbsoluteFill
      style={{
        backgroundColor: "#000000",
        transform: `translate(${shake.x}px, ${shake.y}px) scale(${punch})`,
      }}
    >
      {scenes.map((src, index) => {
        const w = windows[index];
        const lenPrev = w.start - w.from; // incoming transition length
        const lenNext =
          index < count - 1 ? windows[index + 1].start - windows[index + 1].from : 0;

        const entrance: Entrance =
          index === 0
            ? { kind: "fade", len: Math.min(10, w.duration) }
            : { kind: transitionKind(index - 1), len: lenPrev };

        const exit: Exit | null =
          index < count - 1 && lenNext > 0 && transitionKind(index) === "punch"
            ? { kind: "punch", len: lenNext }
            : null;

        return (
          <Sequence key={index} from={w.from} durationInFrames={w.duration}>
            <SceneClip
              index={index}
              sceneSrc={src}
              layer={layers[index] ?? null}
              sceneVideo={sceneVideos[index] ?? null}
              tint={sceneTints[index] ?? FALLBACK_TINT}
              frames={w.duration}
              shots={shotsByScene[index]}
              entrance={entrance}
              exit={exit}
              effectHint={sceneEffects !== null ? sceneEffects[index] ?? null : null}
              motion={motion}
            />
          </Sequence>
        );
      })}
    </AbsoluteFill>
  );
};
