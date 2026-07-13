import type { MotionConfig, ShortProps } from "./types";

// Static composition defaults (studio + fallback). run.py overrides every value
// via inputProps derived from pipeline/config.json (the single source of truth).
export const FPS = 30;
export const WIDTH = 1080;
export const HEIGHT = 1920;
export const FALLBACK_SECONDS = 60;

// Everything on, subtle. Mirrors config.json -> "motion". These are the PUNCHY
// baseline amplitudes; Short.tsx runs resolveMotion() which folds in the smooth
// profile (the default style) before any component reads them.
export const defaultMotion: MotionConfig = {
  style: "smooth",
  parallax: {
    enable: true,
    bgScale: 1.08,
    bgDriftPx: 16,
    fgDriftMultiplier: 2.7,
    fgZoomPct: 1.5,
    ease: false,
  },
  transitions: {
    enable: true,
    frames: 12,
    cellPx: 24,
    smooth: false,
    punchEase: false,
    sceneImpactGain: 0.6,
  },
  effects: {
    enable: true,
    particlesCount: 16,
    particleSizePx: 3,
    rayCount: 3,
    vignetteStrength: 0.38,
    tempSwayPct: 3,
  },
  shake: {
    enable: true,
    px: 4,
    frames: 2,
    sentenceGapSeconds: 0.5,
    onSceneStart: true,
    onShotCut: true,
    onSentenceStart: true,
    ease: false,
  },
  captions: {
    popScale: 1.12,
    settleScale: 1.06,
    entrancePx: 8,
    entranceFrames: 3,
    popFrames: 4,
    overshoot: true,
  },
  mascot: {
    flapHz: 7,
    leanDeg: 2,
    squashPct: 3,
    breathPct: 1,
    entranceFrames: 21,
    swayHz: 5 / (2 * Math.PI),
    entranceDamping: 12,
  },
  shots: {
    enable: true,
    minSeconds: 3,
    maxSeconds: 5,
    detailZoomMin: 1.35,
    detailZoomMax: 1.5,
    altZoomMin: 1.15,
    altZoomMax: 1.25,
    wideZoom: 1.08,
    pushPct: 0.06,
    driftPct: 3,
    maxZoom: 1.6,
    ease: false,
  },
  hook: {
    enable: true,
    cardInFrame: 2,
    cardHoldFrame: 12,
    cardOutFrame: 30,
    punchFrame: 36,
    punchScale: 1.18,
    headStartFrac: 0.15,
    cardFontPx: 150,
    punchRiseFrames: 2,
    punchBackFrames: 10,
    punchSpring: false,
  },
  emphasis: {
    enable: true,
    fontSizePx: 140,
    yPct: 33,
    holdFrames: 12,
    color: "#ffe14d",
    outlineColor: "#000000",
    outlinePx: 12,
    riseFrames: 3,
    fallFrames: 4,
    overshoot: true,
    driftUpPx: 0,
    flashOpacity: 0.08,
    flashFrames: 1,
  },
};

export const defaultProps: ShortProps = {
  fps: FPS,
  width: WIDTH,
  height: HEIGHT,
  audioDuration: FALLBACK_SECONDS,
  audioSrc: "render/voice.mp3",
  musicSrc: null,
  musicVolume: 0.18,
  musicDuck: {
    noSpeech: 0.35,
    underSpeech: 0.15,
    punchline: 0.02,
  },
  sfx: null,
  previewSrc: null,
  previewWord: "",
  hookWords: [],
  emphasisPops: [],
  callouts: [],
  sceneStarts: null,
  mascotSrc: "render/mascot.png",
  mascotHalfSrc: null,
  mascotOpenSrc: null,
  mascotBlinkSrc: null,
  mascotSizePx: 320,
  scenes: [
    "render/scene_1.png",
    "render/scene_2.png",
    "render/scene_3.png",
    "render/scene_4.png",
    "render/scene_5.png",
  ],
  layers: [null, null, null, null, null],
  sceneVideos: [null, null, null, null, null],
  sceneTints: ["#c8a878", "#c8a878", "#c8a878", "#c8a878", "#c8a878"],
  sceneEffects: null,
  endCard: null,
  words: [],
  captions: {
    wordsPerGroup: 1,
    fontSizePx: 132,
    bottomOffsetPx: 420,
    position: "bottom",
    topOffsetPx: 150,
    activeColor: "#ffe14d",
    idleColor: "#ffffff",
    outlineColor: "#000000",
    outlinePx: 12,
    minDisplayFrames: 5,
    emphasisWords: [],
  },
  motion: defaultMotion,
};

export const durationFromProps = (props: ShortProps): number =>
  Math.ceil(props.audioDuration * props.fps) +
  props.fps +
  (props.endCard !== null ? Math.ceil(props.endCard.seconds * props.fps) : 0);
