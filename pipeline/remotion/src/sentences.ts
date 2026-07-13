import type { Word } from "./types";

// A "sentence start" is the first word overall, plus any word that begins after a
// silence longer than gapSeconds. These moments drive the impact micro-shake and
// phase the mascot's body language, so they are computed once from the word
// timings (fully deterministic).
export const sentenceStartTimes = (
  words: readonly Word[],
  gapSeconds: number,
): readonly number[] =>
  words.reduce<readonly number[]>((acc, word, index) => {
    if (index === 0) {
      return [word.start];
    }
    const previous = words[index - 1];
    if (word.start - previous.end > gapSeconds) {
      return [...acc, word.start];
    }
    return acc;
  }, []);
