import type { MotionConfig, MotionStyle } from "./types";

// Single resolution point for the two motion style profiles. run.py passes the
// PUNCHY baseline amplitudes (from config.json) plus a `style` selector; this
// helper folds the selected profile into ONE fully-populated MotionConfig so no
// component has to branch on the style string itself. The smooth profile keeps
// every event (cut density unchanged) but replaces the abrupt 1-2 frame curves
// with eased ones. All smooth constants live here and nowhere else.

const asStyle = (value: MotionStyle | undefined): MotionStyle =>
  value === "punchy" ? "punchy" : "smooth";

// PUNCHY: preserve the original hard-cut behaviour byte-for-byte. Only the new
// behaviour fields are filled in; every amplitude still comes from the raw props.
const resolvePunchy = (raw: MotionConfig): MotionConfig => ({
  ...raw,
  style: "punchy",
  parallax: { ...raw.parallax, ease: false },
  transitions: { ...raw.transitions, smooth: false, punchEase: false, sceneImpactGain: 0.6 },
  shake: {
    ...raw.shake,
    onSceneStart: true,
    onShotCut: true,
    onSentenceStart: true,
    ease: false,
  },
  captions: { ...raw.captions, popFrames: 4, overshoot: true },
  mascot: { ...raw.mascot, swayHz: 5 / (2 * Math.PI), entranceDamping: 12 },
  shots: { ...raw.shots, ease: false },
  hook: { ...raw.hook, punchRiseFrames: 2, punchBackFrames: 10, punchSpring: false },
  emphasis: {
    ...raw.emphasis,
    riseFrames: 3,
    fallFrames: 4,
    overshoot: true,
    driftUpPx: 0,
    flashOpacity: 0.08,
    flashFrames: 1,
  },
});

// SMOOTH (default): same events, cinematic curves. Micro-shake only survives at
// scene starts (2px eased bump); shot-cut and sentence-start shakes are off. The
// hook punch, camera moves, caption pops, mascot and transitions are all eased.
const resolveSmooth = (raw: MotionConfig): MotionConfig => ({
  ...raw,
  style: "smooth",
  parallax: { ...raw.parallax, ease: true },
  transitions: {
    ...raw.transitions,
    frames: 16,
    smooth: true,
    punchEase: true,
    sceneImpactGain: 0.4,
  },
  shake: {
    ...raw.shake,
    px: 2,
    frames: 4,
    onSceneStart: true,
    onShotCut: false,
    onSentenceStart: false,
    ease: true,
  },
  captions: {
    ...raw.captions,
    popScale: 1.04,
    settleScale: 1.04,
    entranceFrames: 4,
    popFrames: 3,
    overshoot: false,
  },
  mascot: {
    ...raw.mascot,
    squashPct: 0,
    leanDeg: 1,
    swayHz: 0.5,
    entranceDamping: 18,
  },
  shots: { ...raw.shots, ease: true },
  hook: {
    ...raw.hook,
    punchScale: 1.12,
    punchRiseFrames: 7,
    punchBackFrames: 11,
    punchSpring: true,
  },
  emphasis: {
    ...raw.emphasis,
    riseFrames: 6,
    fallFrames: 6,
    overshoot: false,
    driftUpPx: 40,
    flashOpacity: 0.04,
    flashFrames: 3,
  },
});

export const resolveMotion = (raw: MotionConfig): MotionConfig =>
  asStyle(raw.style) === "punchy" ? resolvePunchy(raw) : resolveSmooth(raw);
