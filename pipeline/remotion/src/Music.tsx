import { Audio, staticFile, useVideoConfig } from "remotion";
import type { MusicDuck, Word } from "./types";

type MusicProps = {
  readonly src: string | null;
  readonly duck: MusicDuck;
  readonly words: readonly Word[];
  readonly punchlineFrame: number;
  readonly calloutBeats: readonly number[];
};

// Background music whose volume tracks narration activity: it lifts in the gaps
// and ducks under speech, then drops to near-zero for the punchline beat AND for
// each story-callout event beat (the slam of a scoreboard / shock). Fully
// null-safe: with no music file present (the common case) it renders nothing.
export const Music: React.FC<MusicProps> = ({ src, duck, words, punchlineFrame, calloutBeats }) => {
  const { fps } = useVideoConfig();
  if (src === null) {
    return null;
  }

  const preRoll = Math.round(0.4 * fps);
  const postRoll = Math.round(0.15 * fps);
  // A shorter ~0.35s duck window for callout slams (0.2s in, 0.15s out).
  const calloutPre = Math.round(0.2 * fps);
  const calloutPost = Math.round(0.15 * fps);

  const inWindow = (frame: number, center: number, pre: number, post: number): boolean =>
    frame >= center - pre && frame <= center + post;

  const volume = (frame: number): number => {
    if (punchlineFrame >= 0 && inWindow(frame, punchlineFrame, preRoll, postRoll)) {
      return duck.punchline;
    }
    if (calloutBeats.some((beat) => inWindow(frame, beat, calloutPre, calloutPost))) {
      return duck.punchline;
    }
    const t = frame / fps;
    const near = words.some((word) => t >= word.start - 0.3 && t <= word.end + 0.3);
    return near ? duck.underSpeech : duck.noSpeech;
  };

  return <Audio src={staticFile(src)} volume={volume} loop />;
};
