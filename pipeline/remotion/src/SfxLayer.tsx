import { Audio, Sequence, staticFile, useVideoConfig } from "remotion";
import { sceneWindows } from "./layout";
import type { EmphasisPop, MotionConfig, SfxProps } from "./types";

type SfxLayerProps = {
  readonly sfx: SfxProps | null;
  readonly motion: MotionConfig;
  readonly sceneCount: number;
  readonly sceneStarts: readonly number[] | null;
  readonly durationInFrames: number;
  readonly emphasisPops: readonly EmphasisPop[];
  readonly calloutBeats: readonly number[];
  readonly punchlineFrame: number;
};

type HitProps = {
  readonly src: string;
  readonly from: number;
  readonly durationInFrames: number;
  readonly gain: number;
};

// One placed SFX: an <Audio> clamped inside its own <Sequence> so it fires at a
// single beat and never bleeds across the whole timeline.
const Hit: React.FC<HitProps> = ({ src, from, durationInFrames, gain }) => (
  <Sequence from={Math.max(0, from)} durationInFrames={durationInFrames}>
    <Audio src={staticFile(src)} volume={gain} />
  </Sequence>
);

// All the retro 8-bit SFX, placed against the same scene geometry the visuals
// use so every hit lands on its cut / pop / beat. Every gain sits under the
// untouched voice via masterGain. Null-safe: no sfx prop -> nothing renders.
export const SfxLayer: React.FC<SfxLayerProps> = ({
  sfx,
  motion,
  sceneCount,
  sceneStarts,
  durationInFrames,
  emphasisPops,
  calloutBeats,
  punchlineFrame,
}) => {
  const { fps } = useVideoConfig();
  if (sfx === null) {
    return null;
  }

  const gain = (type: number): number => Math.max(0, Math.min(1, sfx.masterGain * type));
  const gWhoosh = gain(sfx.gains.whoosh);
  const gImpact = gain(sfx.gains.impact);
  const gRiser = gain(sfx.gains.riser);
  const gBlip = gain(sfx.gains.blip);
  const gPop = gain(sfx.gains.pop);

  const windows = sceneWindows(sceneCount, durationInFrames, fps, motion, sceneStarts);
  const hook = motion.hook;

  return (
    <>
      {/* Rising tension bed + impact on the cold-open card. */}
      <Hit src={sfx.riser} from={0} durationInFrames={Math.round(1.2 * fps)} gain={gRiser} />
      <Hit src={sfx.impact} from={hook.cardInFrame} durationInFrames={14} gain={gImpact} />

      {/* Snap punch-in: whoosh into it, pop on the hit. */}
      <Hit src={sfx.whooshUp} from={hook.punchFrame - 4} durationInFrames={14} gain={gWhoosh} />
      <Hit src={sfx.pop} from={hook.punchFrame} durationInFrames={8} gain={gPop} />

      {/* Between-scene transitions: whoosh on the cut, soft impact as the scene lands. */}
      {windows.slice(1).map((w) => (
        <Hit
          key={`whoosh-${w.index}`}
          src={w.index % 2 === 0 ? sfx.whooshDown : sfx.whooshUp}
          from={w.from}
          durationInFrames={14}
          gain={gWhoosh}
        />
      ))}
      {windows.slice(1).map((w) => (
        <Hit
          key={`land-${w.index}`}
          src={sfx.impact}
          from={w.start}
          durationInFrames={10}
          gain={gImpact * motion.transitions.sceneImpactGain}
        />
      ))}

      {/* Blip on each keyword pop. */}
      {emphasisPops.map((pop, index) => (
        <Hit
          key={`blip-${index}`}
          src={sfx.blip}
          from={Math.round(pop.start * fps)}
          durationInFrames={6}
          gain={gBlip}
        />
      ))}

      {/* Story-callout event beats (scoreboard / shock): whoosh into the slam, a
          hard impact on the hit. The music ducks around the same frames. */}
      {calloutBeats.map((beat, index) => (
        <Hit
          key={`callout-whoosh-${index}`}
          src={sfx.whooshUp}
          from={beat - 4}
          durationInFrames={14}
          gain={gWhoosh}
        />
      ))}
      {calloutBeats.map((beat, index) => (
        <Hit
          key={`callout-impact-${index}`}
          src={sfx.impact}
          from={beat}
          durationInFrames={16}
          gain={gImpact}
        />
      ))}

      {/* Punchline beat: impact as the final line lands (music ducks around it). */}
      {punchlineFrame >= 0 ? (
        <Hit src={sfx.impact} from={punchlineFrame} durationInFrames={16} gain={gImpact} />
      ) : null}
    </>
  );
};
