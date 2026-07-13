import { AbsoluteFill, Easing, interpolate, useCurrentFrame, useVideoConfig } from "remotion";
import type { CaptionStyle, CaptionsMotionConfig, Word } from "./types";

type CaptionsProps = {
  readonly words: readonly Word[];
  readonly style: CaptionStyle;
  readonly motion: CaptionsMotionConfig;
  readonly hideBeforeFrame?: number;
};

type Group = {
  readonly words: readonly Word[];
  readonly start: number;
  readonly end: number;
  // Effective on-screen start (>= start): pushed later when a preceding short
  // word needed its min-display floor, so single words never strobe.
  readonly shownAt: number;
};

const CLAMP = { extrapolateLeft: "clamp", extrapolateRight: "clamp" } as const;
const EASE_OUT = { ...CLAMP, easing: Easing.out(Easing.cubic) } as const;

// Approx uppercase Arial-Black advance per character as a fraction of font size
// (includes the outline stroke), used to shrink a long single word so it never
// overflows the frame width. Deterministic -> render stays reproducible.
const CHAR_ADVANCE = 0.72;

const normalize = (word: string): string => word.toLowerCase().replace(/[^a-z0-9]+/g, "");
const hasDigit = (word: string): boolean => /[0-9]/.test(word);

const chunk = (words: readonly Word[], size: number, minDisplaySec: number): readonly Group[] => {
  const groups: Group[] = [];
  let prevShownAt = -Infinity;
  for (let i = 0; i < words.length; i += size) {
    const slice = words.slice(i, i + size);
    if (slice.length === 0) {
      continue;
    }
    const start = slice[0].start;
    // Hold each group at least minDisplaySec: if the previous group started so
    // recently that this one would cut it short, delay this group's appearance.
    const shownAt = Math.max(start, prevShownAt + minDisplaySec);
    groups.push({ words: slice, start, end: slice[slice.length - 1].end, shownAt });
    prevShownAt = shownAt;
  }
  return groups;
};

const activeGroup = (groups: readonly Group[], t: number): Group | null => {
  if (groups.length === 0) {
    return null;
  }
  // Last group already shown (by its effective start); keeps a caption on
  // screen continuously with no blank gaps.
  let current: Group | null = null;
  for (const group of groups) {
    if (group.shownAt <= t) {
      current = group;
    } else {
      break;
    }
  }
  return current ?? groups[0];
};

const wordColor = (word: string, style: CaptionStyle): string => {
  const norm = normalize(word);
  const accented = hasDigit(word) || (norm.length > 0 && style.emphasisWords.includes(norm));
  return accented ? style.activeColor : style.idleColor;
};

export const Captions: React.FC<CaptionsProps> = ({
  words,
  style,
  motion,
  hideBeforeFrame = 0,
}) => {
  const frame = useCurrentFrame();
  const { fps, width } = useVideoConfig();
  const t = frame / fps;

  // The cold-open preview card owns the first beat; captions stay out of it.
  if (frame < hideBeforeFrame) {
    return null;
  }

  const size = Math.max(1, style.wordsPerGroup);
  const minDisplaySec = Math.max(0, style.minDisplayFrames) / fps;
  const groups = chunk(words, size, minDisplaySec);
  const group = activeGroup(groups, t);
  if (group === null) {
    return null;
  }

  const shadow = `${style.outlineColor}`;
  const stroke = `${style.outlinePx}px ${style.outlineColor}`;

  // Shrink a lone long word (no spaces to wrap on) so it never overflows.
  const maxTextWidth = width - 120;
  let fontSize = style.fontSizePx;
  if (group.words.length === 1) {
    const chars = Math.max(1, group.words[0].word.length);
    const fitted = maxTextWidth / (chars * CHAR_ADVANCE);
    fontSize = Math.max(64, Math.min(style.fontSizePx, fitted));
  }

  // Group entrance: slide up + fade over a few frames from its EFFECTIVE start.
  const entranceOpts = motion.overshoot ? CLAMP : EASE_OUT;
  const groupAge = frame - group.shownAt * fps;
  const groupOpacity = interpolate(groupAge, [0, motion.entranceFrames], [0, 1], entranceOpts);
  const groupSlide = interpolate(
    groupAge,
    [0, motion.entranceFrames],
    [motion.entrancePx, 0],
    entranceOpts,
  );

  const atTop = style.position === "top";
  return (
    <AbsoluteFill
      style={{
        justifyContent: atTop ? "flex-start" : "flex-end",
        alignItems: "center",
        paddingBottom: atTop ? 0 : style.bottomOffsetPx,
        paddingTop: atTop ? style.topOffsetPx : 0,
        paddingLeft: 60,
        paddingRight: 60,
      }}
    >
      <div
        style={{
          display: "flex",
          flexWrap: "wrap",
          justifyContent: "center",
          gap: `0 ${Math.round(width * 0.035)}px`,
          maxWidth: maxTextWidth,
          fontFamily: "Arial Black, Arial, sans-serif",
          fontWeight: 900,
          fontSize,
          lineHeight: 1.1,
          textAlign: "center",
          textTransform: "uppercase",
          opacity: groupOpacity,
          transform: `translateY(${groupSlide}px)`,
        }}
      >
        {group.words.map((w, index) => {
          // A word is "active" only while it is actually being spoken; drives the
          // gentle scale pop. Colour is decided by digit/emphasis, not timing, so
          // an always-on single word does not sit permanently highlighted.
          const isSpoken = t >= w.start && t < w.end;
          const wordAge = frame - w.start * fps;
          const pop = !isSpoken
            ? 1
            : motion.overshoot
              ? interpolate(wordAge, [0, 2, 4], [1, motion.popScale, motion.settleScale], CLAMP)
              : interpolate(wordAge, [0, motion.popFrames], [1, motion.popScale], EASE_OUT);
          return (
            <span
              key={`${w.word}-${index}`}
              style={{
                color: wordColor(w.word, style),
                WebkitTextStroke: stroke,
                paintOrder: "stroke fill",
                textShadow: `0 6px 0 ${shadow}, 0 0 18px rgba(0,0,0,0.6)`,
                transform: `scale(${pop})`,
                display: "inline-block",
              }}
            >
              {w.word}
            </span>
          );
        })}
      </div>
    </AbsoluteFill>
  );
};
