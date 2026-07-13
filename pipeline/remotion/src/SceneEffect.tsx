import { Particles } from "./Particles";
import { LightRays } from "./LightRays";
import { VignettePulse } from "./VignettePulse";
import type { EffectsConfig } from "./types";

export type EffectKind = "particles" | "rays" | "vignette";

const EFFECT_ORDER: readonly EffectKind[] = ["particles", "rays", "vignette"];

const isEffectKind = (value: string): value is EffectKind =>
  (EFFECT_ORDER as readonly string[]).includes(value);

// Pick one living-scene effect per scene: honour an episode-provided hint when it
// names a valid effect, otherwise rotate deterministically by scene index.
export const effectKind = (index: number, hint: string | null): EffectKind => {
  if (hint !== null && isEffectKind(hint)) {
    return hint;
  }
  return EFFECT_ORDER[index % EFFECT_ORDER.length];
};

type SceneEffectProps = {
  readonly index: number;
  readonly tint: string;
  readonly hint: string | null;
  readonly config: EffectsConfig;
};

export const SceneEffect: React.FC<SceneEffectProps> = ({ index, tint, hint, config }) => {
  const kind = effectKind(index, hint);
  if (kind === "particles") {
    return (
      <Particles
        index={index}
        count={config.particlesCount}
        sizePx={config.particleSizePx}
        tint={tint}
      />
    );
  }
  if (kind === "rays") {
    return <LightRays index={index} count={config.rayCount} tint={tint} />;
  }
  return (
    <VignettePulse
      index={index}
      strength={config.vignetteStrength}
      tempSwayPct={config.tempSwayPct}
    />
  );
};
