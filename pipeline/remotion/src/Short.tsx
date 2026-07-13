import { AbsoluteFill, Audio, Sequence, staticFile, useVideoConfig } from "remotion";
import { useMemo } from "react";
import { calloutBeatFrames, resolveCallouts } from "./callouts";
import { Captions } from "./Captions";
import { EmphasisPops } from "./EmphasisPops";
import { EndCard } from "./EndCard";
import { HookCard } from "./HookCard";
import { Mascot } from "./Mascot";
import { Music } from "./Music";
import { PreviewCard } from "./PreviewCard";
import { resolveMotion } from "./motionStyle";
import { Scenes } from "./Scenes";
import { sentenceStartTimes } from "./sentences";
import { SfxLayer } from "./SfxLayer";
import { StoryCallouts } from "./StoryCallouts";
import type { MascotFrames, ShortProps } from "./types";

export const Short: React.FC<ShortProps> = ({
  audioDuration,
  audioSrc,
  musicSrc,
  musicDuck,
  sfx,
  previewSrc,
  previewWord,
  hookWords,
  emphasisPops,
  callouts,
  sceneStarts,
  mascotSrc,
  mascotHalfSrc,
  mascotOpenSrc,
  mascotBlinkSrc,
  mascotSizePx,
  scenes,
  layers,
  sceneVideos,
  sceneTints,
  sceneEffects,
  endCard,
  words,
  captions,
  motion: rawMotion,
}) => {
  const { durationInFrames, fps } = useVideoConfig();

  // Fold the selected style profile into one resolved config the whole tree reads.
  const motion = useMemo(() => resolveMotion(rawMotion), [rawMotion]);

  const mascotFrames: MascotFrames | null =
    mascotSrc === null
      ? null
      : {
          closed: mascotSrc,
          half: mascotHalfSrc,
          open: mascotOpenSrc,
          blink: mascotBlinkSrc,
        };

  // Last sentence start (via the word-gap logic) drives the punchline beat:
  // the music ducks to near-zero just before it and an impact lands on it.
  const sentenceStarts = sentenceStartTimes(words, motion.shake.sentenceGapSeconds);
  const punchlineFrame =
    sentenceStarts.length > 0
      ? Math.round(sentenceStarts[sentenceStarts.length - 1] * fps)
      : -1;

  // Resolve authored callouts once (baked timing + overlap-delay), then derive the
  // event beats the audio layers punch/duck on. Shared so band, SFX and music
  // stay frame-aligned.
  const resolvedCallouts = useMemo(() => resolveCallouts(callouts, fps), [callouts, fps]);
  const calloutBeats = useMemo(
    () => calloutBeatFrames(resolvedCallouts, punchlineFrame, fps),
    [resolvedCallouts, punchlineFrame, fps],
  );

  return (
    <AbsoluteFill style={{ backgroundColor: "#000000" }}>
      <Scenes
        scenes={scenes}
        layers={layers}
        sceneVideos={sceneVideos}
        sceneTints={sceneTints}
        sceneEffects={sceneEffects}
        sceneStarts={sceneStarts}
        words={words}
        motion={motion}
        durationInFrames={durationInFrames}
      />

      {/* Bottom scrim so captions stay legible over any scene. */}
      <AbsoluteFill
        style={{
          background:
            "linear-gradient(to bottom, rgba(0,0,0,0) 45%, rgba(0,0,0,0.35) 70%, rgba(0,0,0,0.72) 100%)",
        }}
      />

      <EmphasisPops pops={emphasisPops} motion={motion.emphasis} />
      <StoryCallouts callouts={resolvedCallouts} />
      {/* The preview card IS the cold-open hook when a portrait exists; the
          text-only hook card is the null-safe fallback. */}
      {previewSrc !== null ? (
        <PreviewCard src={previewSrc} word={previewWord} motion={motion.hook} />
      ) : (
        <HookCard words={hookWords} motion={motion.hook} />
      )}

      {mascotFrames !== null && (
        <Mascot frames={mascotFrames} sizePx={mascotSizePx} words={words} motion={motion.mascot} />
      )}
      <Captions
        words={words}
        style={captions}
        motion={motion.captions}
        hideBeforeFrame={previewSrc !== null && motion.hook.enable ? motion.hook.cardOutFrame : 0}
      />

      {endCard !== null && (
        <Sequence
          from={Math.ceil(audioDuration * fps) + Math.round(0.4 * fps)}
          durationInFrames={Math.ceil(endCard.seconds * fps) + fps}
        >
          <EndCard card={endCard} />
        </Sequence>
      )}

      <Audio src={staticFile(audioSrc)} />
      <Music
        src={musicSrc}
        duck={musicDuck}
        words={words}
        punchlineFrame={punchlineFrame}
        calloutBeats={calloutBeats}
      />
      <SfxLayer
        sfx={sfx}
        motion={motion}
        sceneCount={scenes.length}
        sceneStarts={sceneStarts}
        durationInFrames={durationInFrames}
        emphasisPops={emphasisPops}
        calloutBeats={calloutBeats}
        punchlineFrame={punchlineFrame}
      />
    </AbsoluteFill>
  );
};
