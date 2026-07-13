import { AbsoluteFill, Audio, Img, interpolate, staticFile, useCurrentFrame, useVideoConfig } from "remotion";
import type { EndCardData } from "./types";

type EndCardProps = {
  readonly card: EndCardData;
};

const CLAMP = { extrapolateLeft: "clamp", extrapolateRight: "clamp" } as const;

// Full-bleed subscribe end-card (kisa-style closer): brand-dark ground, mascot
// bust, channel lockup and a SUBSCRIBE pill. Rendered inside a Sequence that
// starts when the narration ends, so frame 0 here = card start. Opaque by
// design: it covers whatever the stretched last scene shows underneath.
export const EndCard: React.FC<EndCardProps> = ({ card }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const fadeIn = interpolate(frame, [0, 6], [0, 1], CLAMP);
  const rise = interpolate(frame, [0, 8], [26, 0], CLAMP);
  // Subscribe pill pops in a beat later, with a small settle.
  const pillScale = interpolate(frame, [8, 12, 15], [0, 1.12, 1], CLAMP);
  // Gentle mascot breathing so the card does not read as a freeze-frame.
  const breath = 1 + 0.012 * Math.sin((frame / fps) * 2 * Math.PI * 0.9);

  const pixelRow = (top: boolean) => (
    <div
      style={{
        position: "absolute",
        left: 0,
        right: 0,
        [top ? "top" : "bottom"]: 56,
        display: "flex",
        justifyContent: "center",
        gap: 14,
      }}
    >
      {Array.from({ length: 9 }, (_unused, i) => (
        <div
          key={i}
          style={{
            width: 14,
            height: 14,
            background: "#f49b33",
            opacity: i % 3 === 0 ? 0.9 : i % 2 === 0 ? 0.5 : 0.25,
          }}
        />
      ))}
    </div>
  );

  return (
    <AbsoluteFill style={{ backgroundColor: "#1a120c", opacity: fadeIn }}>
      {pixelRow(true)}
      {pixelRow(false)}
      <AbsoluteFill
        style={{
          justifyContent: "center",
          alignItems: "center",
          gap: 34,
          transform: `translateY(${rise}px)`,
        }}
      >
        <Img
          src={staticFile(card.imageSrc)}
          style={{
            width: 460,
            height: 460,
            imageRendering: "pixelated",
            transform: `scale(${breath})`,
          }}
        />
        <div
          style={{
            fontFamily: "Menlo, 'Courier New', monospace",
            fontWeight: 700,
            fontSize: 76,
            letterSpacing: "0.08em",
            color: "#f6e6c8",
            textAlign: "center",
          }}
        >
          {card.title}
        </div>
        <div
          style={{
            fontFamily: "Menlo, 'Courier New', monospace",
            fontWeight: 700,
            fontSize: 40,
            letterSpacing: "0.18em",
            color: "#f49b33",
            textAlign: "center",
          }}
        >
          {card.subtitle}
        </div>
        <div
          style={{
            marginTop: 10,
            transform: `scale(${pillScale})`,
            background: "#e02f2f",
            color: "#ffffff",
            fontFamily: "Arial Black, Arial, sans-serif",
            fontWeight: 900,
            fontSize: 58,
            letterSpacing: "0.05em",
            padding: "22px 74px",
            borderRadius: 18,
            boxShadow: "0 10px 0 rgba(0,0,0,0.45)",
          }}
        >
          {card.button}
        </div>
      </AbsoluteFill>
      {card.voiceSrc !== null && <Audio src={staticFile(card.voiceSrc)} />}
    </AbsoluteFill>
  );
};
