export type Word = {
  readonly word: string;
  readonly start: number;
  readonly end: number;
};

export type MascotFrames = {
  readonly closed: string;
  readonly half: string | null;
  readonly open: string | null;
  readonly blink: string | null;
};

export type CaptionStyle = {
  readonly wordsPerGroup: number;
  readonly fontSizePx: number;
  readonly bottomOffsetPx: number;
  // "top" = kisa-style small word near the top edge; "bottom" = legacy placement.
  readonly position: "bottom" | "top";
  readonly topOffsetPx: number;
  readonly activeColor: string;
  readonly idleColor: string;
  readonly outlineColor: string;
  readonly outlinePx: number;
  // Kisa single-word mode: a shown group is held at least this many frames so
  // fast/short words never strobe (later groups shift slightly later).
  readonly minDisplayFrames: number;
  // Normalized (lowercase, alnum-only) words painted in activeColor; any word
  // containing a digit is also accented. Everything else renders in idleColor.
  readonly emphasisWords: readonly string[];
};

// A pair of pre-rendered parallax plates for one scene. null when layers.py could
// not cut this scene (Remotion then falls back to enhanced Ken Burns).
export type SceneLayer = {
  readonly fg: string;
  readonly bg: string;
};

// A hero-scene video clip (animate.py). null for scenes that keep their still.
// durationInSeconds is the probed clip length, used to size the loop / playthrough
// exactly to the clip.
//   mode "boomerang": the mp4 is a pre-baked forward+reverse boomerang, so a plain
//     <Loop> restarts on a turnaround with an invisible seam.
//   mode "playonce": a one-way action clip (first-last-frame). It plays once, then
//     crossfades to `stillSrc` (which IS the clip's end frame) so the hold is
//     seamless by construction and never restarts the action.
export type SceneVideo = {
  readonly src: string;
  readonly durationInSeconds: number;
  readonly mode: "boomerang" | "playonce";
  readonly stillSrc: string;
};

// Subscribe end-card appended after the narration. null = no card (legacy).
export type EndCardData = {
  readonly imageSrc: string;
  readonly voiceSrc: string | null;
  readonly seconds: number;
  readonly title: string;
  readonly subtitle: string;
  readonly button: string;
};

// One of the two motion style profiles. "punchy" keeps the original hard-cut
// amplitudes; "smooth" eases every curve while keeping the same cut density.
export type MotionStyle = "smooth" | "punchy";

export type ParallaxConfig = {
  readonly enable: boolean;
  readonly bgScale: number;
  readonly bgDriftPx: number;
  readonly fgDriftMultiplier: number;
  readonly fgZoomPct: number;
  readonly ease: boolean; // easeInOut the drift so it has no velocity jump at cuts
};

export type TransitionsConfig = {
  readonly enable: boolean;
  readonly frames: number;
  readonly cellPx: number;
  readonly smooth: boolean; // longer, eased dissolve/wipe/zoom-punch windows
  readonly punchEase: boolean; // eased zoom-punch scale, no per-frame jolt
  readonly sceneImpactGain: number; // multiplier on the SFX impact as a scene lands
};

export type EffectsConfig = {
  readonly enable: boolean;
  readonly particlesCount: number;
  readonly particleSizePx: number;
  readonly rayCount: number;
  readonly vignetteStrength: number;
  readonly tempSwayPct: number;
};

export type ShakeConfig = {
  readonly enable: boolean;
  readonly px: number;
  readonly frames: number;
  readonly sentenceGapSeconds: number;
  readonly onSceneStart: boolean; // fire the impact bump at each scene start
  readonly onShotCut: boolean; // fire at every within-scene hard shot cut
  readonly onSentenceStart: boolean; // fire on the first word of each sentence
  readonly ease: boolean; // eased decay bump instead of an alternating rattle
};

// Multi-crop shots: split each scene into 2-3 hard-cut shots of the same image
// (wide -> detail punch-in -> alternate crop) so the frame changes every few
// seconds instead of holding one static shot for the whole scene.
export type ShotsConfig = {
  readonly enable: boolean;
  readonly minSeconds: number;
  readonly maxSeconds: number;
  readonly detailZoomMin: number;
  readonly detailZoomMax: number;
  readonly altZoomMin: number;
  readonly altZoomMax: number;
  readonly wideZoom: number;
  readonly pushPct: number;
  readonly driftPct: number;
  readonly maxZoom: number;
  readonly ease: boolean; // easeInOut every push/pull/lateral move (no velocity jumps)
};

// First-1.5s hook: a cold-open title card, an already-moving first shot, and a
// snap punch-in a beat later.
export type HookConfig = {
  readonly enable: boolean;
  readonly cardInFrame: number;
  readonly cardHoldFrame: number;
  readonly cardOutFrame: number;
  readonly punchFrame: number;
  readonly punchScale: number;
  readonly headStartFrac: number;
  readonly cardFontPx: number;
  readonly punchRiseFrames: number; // frames to ramp 1.0 -> punchScale
  readonly punchBackFrames: number; // frames to ease punchScale -> 1.0
  readonly punchSpring: boolean; // easeOut ramp (smooth) vs linear step (punchy)
};

// Sparse keyword pops: a big accent-yellow word slam in the upper-middle zone,
// separate from the karaoke captions at the bottom.
export type EmphasisConfig = {
  readonly enable: boolean;
  readonly fontSizePx: number;
  readonly yPct: number;
  readonly holdFrames: number;
  readonly color: string;
  readonly outlineColor: string;
  readonly outlinePx: number;
  readonly riseFrames: number; // scale-in duration
  readonly fallFrames: number; // fade + drift-out duration
  readonly overshoot: boolean; // scale-in overshoot (punchy) vs soft settle (smooth)
  readonly driftUpPx: number; // upward drift on the fade-out
  readonly flashOpacity: number; // additive white-flash peak opacity (0 = off)
  readonly flashFrames: number; // flash fade length in frames
};

export type CaptionsMotionConfig = {
  readonly popScale: number;
  readonly settleScale: number;
  readonly entrancePx: number;
  readonly entranceFrames: number;
  readonly popFrames: number; // active-word scale ease duration
  readonly overshoot: boolean; // pop past popScale then settle (punchy) vs gentle ease (smooth)
};

export type MascotMotionConfig = {
  readonly flapHz: number;
  readonly leanDeg: number;
  readonly squashPct: number;
  readonly breathPct: number;
  readonly entranceFrames: number;
  readonly swayHz: number; // talking body-sway frequency
  readonly entranceDamping: number; // spring damping (higher = softer single overshoot)
};

export type MotionConfig = {
  readonly style: MotionStyle;
  readonly parallax: ParallaxConfig;
  readonly transitions: TransitionsConfig;
  readonly effects: EffectsConfig;
  readonly shake: ShakeConfig;
  readonly captions: CaptionsMotionConfig;
  readonly mascot: MascotMotionConfig;
  readonly shots: ShotsConfig;
  readonly hook: HookConfig;
  readonly emphasis: EmphasisConfig;
};

// One synthesized keyword pop, timed to the narration (seconds).
export type EmphasisPop = {
  readonly word: string;
  readonly start: number;
};

// Story callout styles. scoreboard = full-width event band; label = small corner
// tag; shock = scoreboard + red edge flash + a 1-frame shake.
export type CalloutStyle = "scoreboard" | "label" | "shock";

// One coloured run inside a callout headline (e.g. "USA" white, "ENGLAND" red) so
// team names read unambiguously without parsing the fixture text.
export type CalloutSpan = {
  readonly text: string;
  readonly color: string;
};

// One authored story callout, resolved by run.py from an episode.json anchor to a
// composition frame. The on-screen headline layer (who vs who / what just
// happened) that a swiping viewer reads without parsing the narration. When
// `spans` is present it renders each coloured run in place of the flat `text`.
export type Callout = {
  readonly frame: number;
  readonly text: string;
  readonly style: CalloutStyle;
  readonly spans?: readonly CalloutSpan[];
};

// A Callout after resolveCallouts(): its start frame may be pushed later to avoid
// overlapping the previous callout, and its per-style timing is baked to frames.
export type ResolvedCallout = Callout & {
  readonly inFrames: number;
  readonly holdFrames: number;
  readonly outFrames: number;
  readonly life: number;
};

// Per-type 8-bit SFX gains (0..1). Multiplied by masterGain, so the whole layer
// sits clearly under the untouched voice.
export type SfxGains = {
  readonly whoosh: number;
  readonly impact: number;
  readonly riser: number;
  readonly blip: number;
  readonly pop: number;
};

// staticFile-relative paths to the synthesized WAVs plus their gains. null when
// sfx.py has not produced the files (render stays silent-of-sfx, never fails).
export type SfxProps = {
  readonly masterGain: number;
  readonly gains: SfxGains;
  readonly whooshUp: string;
  readonly whooshDown: string;
  readonly impact: string;
  readonly riser: string;
  readonly blip: string;
  readonly pop: string;
};

// Music volume tiers driven by narration activity, plus the punchline duck.
export type MusicDuck = {
  readonly noSpeech: number;
  readonly underSpeech: number;
  readonly punchline: number;
};

export type ShortProps = {
  readonly fps: number;
  readonly width: number;
  readonly height: number;
  readonly audioDuration: number;
  readonly audioSrc: string;
  readonly musicSrc: string | null;
  readonly musicVolume: number;
  readonly musicDuck: MusicDuck;
  readonly sfx: SfxProps | null;
  // Cold-open preview card: a full-screen still (out/thumb_portrait_base.png,
  // staged into render/) with the burned thumbnail word. When previewSrc is
  // present it REPLACES the text-only hook card (the preview IS the first beat);
  // null falls back to hookWords. previewWord is the burned headline word.
  readonly previewSrc: string | null;
  readonly previewWord: string;
  readonly hookWords: readonly string[];
  readonly emphasisPops: readonly EmphasisPop[];
  // Authored story callouts (run.py resolves episode.json anchors -> frames). When
  // present they replace the emphasis-pops headline layer for this episode.
  readonly callouts: readonly Callout[];
  // Per-scene narration start times (seconds), so scenes cut exactly when their
  // line begins. null falls back to an equal split.
  readonly sceneStarts: readonly number[] | null;
  readonly mascotSrc: string | null;
  readonly mascotHalfSrc: string | null;
  readonly mascotOpenSrc: string | null;
  readonly mascotBlinkSrc: string | null;
  readonly mascotSizePx: number;
  readonly scenes: readonly string[];
  readonly layers: readonly (SceneLayer | null)[];
  readonly sceneVideos: readonly (SceneVideo | null)[];
  readonly sceneTints: readonly string[];
  readonly sceneEffects: readonly string[] | null;
  readonly endCard: EndCardData | null;
  readonly words: readonly Word[];
  readonly captions: CaptionStyle;
  readonly motion: MotionConfig;
};
