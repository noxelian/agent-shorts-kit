import {
  AbsoluteFill,
  Easing,
  Img,
  interpolate,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import type { HookConfig } from "./types";

type PreviewCardProps = {
  readonly src: string;
  readonly word: string;
  readonly motion: HookConfig;
};

const CLAMP = { extrapolateLeft: "clamp", extrapolateRight: "clamp" } as const;
const EASE_OUT = { ...CLAMP, easing: Easing.out(Easing.cubic) } as const;

// Frames the pixel-dissolve out into scene 1 takes. The card holds full-screen
// until (cardOutFrame - DISSOLVE), then fades to reveal scene 1 underneath (which
// has already faded up from black), so the hand-off reads as a quick hard cut.
const DISSOLVE = 6;

// A number/scoreline burns in the accent yellow (matches the thumbnail rule:
// digit -> accent), everything else white.
const wordColor = (word: string): string =>
  /[0-9]/.test(word) ? "#ffe14d" : "#ffffff";

// Thumbnail-first cold open: the preview IS the first beat. The video opens on the
// thumbnail portrait, cover-fit full-screen, with the SAME burned word style as
// the baked thumbnail (big pixel caps, hard outline, bottom third) rendered in
// Remotion text. A fast eased zoom (1.0 -> 1.06) plus the frame-2 impact SFX
// (fired by SfxLayer) sell the slam; it dissolves into scene 1 at ~1.1s.
export const PreviewCard: React.FC<PreviewCardProps> = ({ src, word, motion }) => {
  const frame = useCurrentFrame();
  const { height, width } = useVideoConfig();

  const outFrame = motion.cardOutFrame;
  if (frame > outFrame) {
    return null;
  }

  const zoom = interpolate(frame, [0, outFrame], [1.0, 1.06], EASE_OUT);
  const opacity = interpolate(frame, [outFrame - DISSOLVE, outFrame], [1, 0], CLAMP);

  // Word geometry: bottom third, but BELOW the karaoke caption zone. Font size
  // auto-fits the frame width (Arial Black caps ≈ 0.74em advance) so a longer
  // word like UPSET! never clips at the edges.
  const fontSize = Math.round(
    Math.min(height * 0.155, (width - 110) / (Math.max(1, word.length) * 0.74)),
  );
  const stroke = Math.max(6, Math.round(fontSize * 0.11));

  return (
    <AbsoluteFill style={{ opacity, backgroundColor: "#000000" }}>
      <AbsoluteFill style={{ transform: `scale(${zoom})`, transformOrigin: "50% 50%" }}>
        <Img
          src={staticFile(src)}
          style={{
            width: "100%",
            height: "100%",
            objectFit: "cover",
            imageRendering: "pixelated",
          }}
        />
      </AbsoluteFill>

      {/* Faint bottom scrim so the burned word reads over a busy portrait. */}
      <AbsoluteFill
        style={{
          background:
            "linear-gradient(to bottom, rgba(0,0,0,0) 55%, rgba(0,0,0,0.45) 82%, rgba(0,0,0,0.72) 100%)",
        }}
      />

      <AbsoluteFill
        style={{
          justifyContent: "flex-end",
          alignItems: "center",
          paddingBottom: Math.round(height * 0.13),
          paddingLeft: 40,
          paddingRight: 40,
        }}
      >
        <div
          style={{
            fontFamily: "Arial Black, Arial, sans-serif",
            fontWeight: 900,
            fontSize,
            lineHeight: 1.0,
            textAlign: "center",
            textTransform: "uppercase",
            color: wordColor(word),
            WebkitTextStroke: `${stroke}px #000000`,
            paintOrder: "stroke fill",
            textShadow: "0 10px 0 #000000, 0 0 30px rgba(0,0,0,0.7)",
            whiteSpace: "nowrap",
          }}
        >
          {word}
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};
