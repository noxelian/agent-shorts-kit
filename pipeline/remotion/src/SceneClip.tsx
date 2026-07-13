import { AbsoluteFill, Easing, interpolate, Sequence, useCurrentFrame, useVideoConfig } from "remotion";
import type { CSSProperties } from "react";
import { CropShot } from "./CropShot";
import { headStartFrames } from "./hook";
import { Parallax } from "./Parallax";
import { SceneEffect } from "./SceneEffect";
import { SceneVideo } from "./SceneVideo";
import { dissolveMask, wipeMask } from "./transitions";
import type { TransitionKind } from "./transitions";
import type { Shot } from "./shots";
import type { MotionConfig, SceneLayer, SceneVideo as SceneVideoData } from "./types";

// A scene entrance either fades from black (first scene) or plays the incoming
// half of a transition. The exit only animates for the zoom-punch cut; dissolve
// and wipe are handled entirely by the next scene's entrance reveal on top.
export type EntranceKind = TransitionKind | "fade";

export type Entrance = { readonly kind: EntranceKind; readonly len: number };
export type Exit = { readonly kind: "punch"; readonly len: number };

type SceneClipProps = {
  readonly index: number;
  readonly sceneSrc: string;
  readonly layer: SceneLayer | null;
  readonly sceneVideo: SceneVideoData | null;
  readonly tint: string;
  readonly frames: number;
  readonly shots: readonly Shot[];
  readonly entrance: Entrance;
  readonly exit: Exit | null;
  readonly effectHint: string | null;
  readonly motion: MotionConfig;
};

const CLAMP = { extrapolateLeft: "clamp", extrapolateRight: "clamp" } as const;
const EASE_IN_OUT = { ...CLAMP, easing: Easing.inOut(Easing.cubic) } as const;

const maskStyle = (mask: string): CSSProperties => ({
  maskImage: mask,
  WebkitMaskImage: mask,
  maskRepeat: "no-repeat",
  WebkitMaskRepeat: "no-repeat",
  maskSize: "100% 100%",
  WebkitMaskSize: "100% 100%",
});

export const SceneClip: React.FC<SceneClipProps> = ({
  index,
  sceneSrc,
  layer,
  sceneVideo,
  tint,
  frames,
  shots,
  entrance,
  exit,
  effectHint,
  motion,
}) => {
  const frame = useCurrentFrame();
  const { width, height } = useVideoConfig();

  // A hero video scene renders the clip full-bleed and SKIPS multicrop shots,
  // parallax, and particle effects (the motion already lives in the footage);
  // the between-scene transition wrapper below still applies so cuts blend.
  const effect =
    sceneVideo === null && motion.effects.enable ? (
      <SceneEffect index={index} tint={tint} hint={effectHint} config={motion.effects} />
    ) : null;

  let wrapperStyle: CSSProperties = {};
  let transform = "";
  let opacity = 1;

  const inEntrance = entrance.len > 0 && frame < entrance.len;
  if (inEntrance) {
    const progress = Math.min(1, (frame + 1) / entrance.len);
    if (entrance.kind === "fade") {
      opacity = interpolate(frame, [0, entrance.len], [0, 1], CLAMP);
    } else if (entrance.kind === "punch") {
      const eased = motion.transitions.punchEase
        ? interpolate(progress, [0, 1], [0, 1], EASE_IN_OUT)
        : progress;
      transform = `scale(${1.04 - 0.04 * eased})`;
      opacity = interpolate(frame, [0, motion.transitions.punchEase ? 5 : 3], [0, 1], CLAMP);
    } else {
      const seed = index * 101 + 7;
      wrapperStyle = maskStyle(
        entrance.kind === "dissolve"
          ? dissolveMask(progress, width, height, motion.transitions.cellPx, seed)
          : wipeMask(progress, width, height, motion.transitions.cellPx, seed),
      );
    }
  }

  const exitStart = exit !== null ? frames - exit.len : frames;
  if (exit !== null && frame >= exitStart) {
    const age = frame - exitStart;
    const rawProgress = age / exit.len;
    // Smooth: ease the zoom and drop the 3-frame jolt (it read as a hard twitch).
    const progress = motion.transitions.punchEase
      ? interpolate(rawProgress, [0, 1], [0, 1], EASE_IN_OUT)
      : rawProgress;
    const scale = 1 + 0.06 * progress;
    const jolt =
      !motion.transitions.punchEase && age < 3
        ? ((3 - age) / 3) * 6 * (age % 2 === 0 ? 1 : -1)
        : 0;
    transform = `scale(${scale}) translate(${jolt}px, ${-jolt}px)`;
  }

  const renderShot = (shot: Shot, shotIndex: number) => {
    const headStart =
      index === 0 && shotIndex === 0 ? headStartFrames(shot.len, motion.hook) : 0;
    if (shot.type === "wide" && layer !== null && motion.parallax.enable) {
      return (
        <Parallax
          layer={layer}
          index={index}
          frames={shot.len}
          config={motion.parallax}
          headStart={headStart}
        />
      );
    }
    return <CropShot src={sceneSrc} shot={shot} config={motion.shots} headStart={headStart} />;
  };

  return (
    <AbsoluteFill
      style={{ ...wrapperStyle, transform: transform === "" ? undefined : transform, opacity }}
    >
      {sceneVideo !== null ? (
        <SceneVideo video={sceneVideo} frames={frames} />
      ) : (
        shots.map((shot, shotIndex) => (
          <Sequence key={shotIndex} from={shot.from} durationInFrames={shot.len}>
            {renderShot(shot, shotIndex)}
          </Sequence>
        ))
      )}
      {effect}
    </AbsoluteFill>
  );
};
