import {
  AbsoluteFill,
  Easing,
  Img,
  interpolate,
  Loop,
  OffthreadVideo,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import type { SceneVideo as SceneVideoData } from "./types";

type SceneVideoProps = {
  readonly video: SceneVideoData;
  readonly frames: number; // scene-window length; drives the ken-burns span
};

const CLAMP = { extrapolateLeft: "clamp", extrapolateRight: "clamp" } as const;

// Frames the one-way action clip crossfades to its end still over. The clip's
// last frame IS the still, so the hand-off is seamless by construction.
const CROSSFADE = 6;

const coverStyle = {
  width: "100%",
  height: "100%",
  objectFit: "cover",
  imageRendering: "pixelated",
} as const;

// Full-bleed hero video for one scene, with a gentle 1.0 -> 1.04 ken-burns zoom
// across the whole scene window (OUTSIDE any loop so it spans the scene, not each
// iteration). image-rendering: pixelated keeps the re-pixelated grid hard.
export const SceneVideo: React.FC<SceneVideoProps> = ({ video, frames }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const zoom = interpolate(frame, [0, Math.max(1, frames)], [1, 1.04], {
    ...CLAMP,
    easing: Easing.inOut(Easing.quad),
  });

  const clipFrames = Math.max(1, Math.floor(video.durationInSeconds * fps));

  // One-way action (first-last-frame): play the clip once, then crossfade to the
  // end still and hold it for the rest of the window. No boomerang restart, so a
  // goal reads as a single forward action.
  if (video.mode === "playonce") {
    const videoOpacity = interpolate(
      frame,
      [clipFrames - CROSSFADE, clipFrames],
      [1, 0],
      CLAMP,
    );
    return (
      <AbsoluteFill style={{ transform: `scale(${zoom})`, transformOrigin: "50% 50%" }}>
        <AbsoluteFill>
          <Img src={staticFile(video.stillSrc)} style={coverStyle} />
        </AbsoluteFill>
        <AbsoluteFill style={{ opacity: videoOpacity }}>
          <OffthreadVideo src={staticFile(video.src)} muted style={coverStyle} />
        </AbsoluteFill>
      </AbsoluteFill>
    );
  }

  // Boomerang: the clip is a pre-baked forward+reverse loop, so a restart lands on
  // a turnaround -> the seam is invisible. floor() keeps every iteration strictly
  // inside the clip so a restart never clamps on a frozen last frame.
  return (
    <AbsoluteFill style={{ transform: `scale(${zoom})`, transformOrigin: "50% 50%" }}>
      <Loop durationInFrames={clipFrames}>
        <AbsoluteFill>
          <OffthreadVideo src={staticFile(video.src)} muted style={coverStyle} />
        </AbsoluteFill>
      </Loop>
    </AbsoluteFill>
  );
};
