"""Map ElevenLabs character-level timestamps onto clean word timings.

The with-timestamps endpoint returns, for the *input* text, three parallel
arrays: characters[], character_start_times_seconds[], character_end_times_seconds[].
When the input carries v3 audio tags ([excited], [pause], ...) those bracketed
characters are present in the input and therefore in this alignment, but they
are NOT spoken words. We must:

  1. drop every character that belongs to a `[...]` tag span,
  2. group the remaining characters into words on whitespace,
  3. give each word start = first-char start, end = last-char end.

This yields the exact same {word, start, end} schema align.py produces, so the
rest of the pipeline (captions, emphasis pops) is engine-agnostic.

The mapping is robust to BOTH shapes the API may return: tags still present in
the character stream (stripped here) or already absent (nothing to strip).

Run `python el_align.py` to execute the self-test.
"""
from __future__ import annotations

import re

TAG_RE = re.compile(r"\[[^\]]*\]")


def _tag_char_indices(characters: list[str]) -> set[int]:
    """Indices of characters that fall inside a `[...]` tag span, so their
    timings are excluded from word assembly."""
    text = "".join(characters)
    excluded: set[int] = set()
    for match in TAG_RE.finditer(text):
        excluded.update(range(match.start(), match.end()))
    return excluded


def words_from_alignment(alignment: dict) -> list[dict]:
    """Build [{word, start, end}] from an ElevenLabs alignment block.

    `alignment` is {characters, character_start_times_seconds,
    character_end_times_seconds}. Whitespace separates words; tag characters are
    dropped; consecutive whitespace never yields an empty word.
    """
    characters = alignment.get("characters") or []
    starts = alignment.get("character_start_times_seconds") or []
    ends = alignment.get("character_end_times_seconds") or []
    if not (len(characters) == len(starts) == len(ends)):
        raise ValueError(
            "elevenlabs alignment arrays are ragged: "
            f"{len(characters)} chars / {len(starts)} starts / {len(ends)} ends"
        )

    excluded = _tag_char_indices(characters)
    words: list[dict] = []
    current: list[str] = []
    word_start: float | None = None
    word_end: float | None = None

    def flush() -> None:
        nonlocal current, word_start, word_end
        if current and word_start is not None and word_end is not None:
            words.append({
                "word": "".join(current),
                "start": round(float(word_start), 3),
                "end": round(float(word_end), 3),
            })
        current = []
        word_start = None
        word_end = None

    for i, char in enumerate(characters):
        if i in excluded:
            continue
        if char.isspace():
            flush()
            continue
        if word_start is None:
            word_start = starts[i]
        word_end = ends[i]
        current.append(char)
    flush()
    return words


def _selftest() -> None:
    """Synthetic unit test for the char->word mapping. No API, no quota."""

    def alignment_for(text: str, step: float = 0.1) -> dict:
        chars = list(text)
        starts = [round(i * step, 3) for i in range(len(chars))]
        ends = [round((i + 1) * step, 3) for i in range(len(chars))]
        return {
            "characters": chars,
            "character_start_times_seconds": starts,
            "character_end_times_seconds": ends,
        }

    # 1) Tags present: glued-to-word, mid-sentence pause, trailing whitespace.
    tagged = "[excited]Hello world! [pause] Bye now."
    words = words_from_alignment(alignment_for(tagged))
    got = [w["word"] for w in words]
    assert got == ["Hello", "world!", "Bye", "now."], got
    # "Hello" starts at the 'H' (index 9, after "[excited]"), so 0.9.
    assert abs(words[0]["start"] - 0.9) < 1e-6, words[0]
    # last char '.' is index len-1 -> end == len*step.
    assert abs(words[-1]["end"] - len(tagged) * 0.1) < 1e-6, words[-1]
    # No literal bracket leaked into any word.
    assert not any("[" in w or "]" in w for w in got), got

    # 2) Same words, tags already stripped by the API -> identical tokens.
    plain = "Hello world! Bye now."
    plain_words = [w["word"] for w in words_from_alignment(alignment_for(plain))]
    assert plain_words == got, (plain_words, got)

    # 3) Consecutive whitespace (left by a removed tag) yields no empty words.
    doubled = words_from_alignment(alignment_for("keeper.  One"))
    assert [w["word"] for w in doubled] == ["keeper.", "One"], doubled

    # 4) Word count matches a whitespace tokenization of the clean text.
    clean = TAG_RE.sub("", tagged)
    assert len(words) == len(clean.split()), (len(words), clean.split())

    # 5) Ragged arrays fail loudly.
    try:
        words_from_alignment({"characters": ["a"], "character_start_times_seconds": [],
                              "character_end_times_seconds": []})
    except ValueError:
        pass
    else:  # pragma: no cover
        raise AssertionError("expected ValueError on ragged arrays")

    print("el_align self-test passed:", got)


if __name__ == "__main__":
    _selftest()
