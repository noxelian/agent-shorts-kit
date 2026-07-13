import { AbsoluteFill, Easing, interpolate, Sequence, useCurrentFrame, useVideoConfig } from "remotion";
import type { CSSProperties } from "react";
import type { ResolvedCallout } from "./types";

type StoryCalloutsProps = {
  readonly callouts: readonly ResolvedCallout[];
};

const CLAMP = { extrapolateLeft: "clamp", extrapolateRight: "clamp" } as const;
const EASE_OUT = { ...CLAMP, easing: Easing.out(Easing.cubic) } as const;

// Shared caption font stack so callouts read as the same pixel-history headline
// family as the karaoke captions.
const FONT_FAMILY = "Arial Black, Arial, sans-serif";
const SCOREBOARD_ACCENT = "#ffe14d";
const SHOCK_ACCENT = "#ff2e2e";

// Vertical anchor for the event band: upper-middle, well clear of the bottom-700px
// caption zone and never overlapping the karaoke text.
const BAND_TOP_FRAC = 0.26;
const LABEL_TOP_FRAC = 0.13;

type Envelope = {
  readonly opacity: number;
  readonly scaleIn: number;
  readonly slideIn: number;
};

// Common in/hold/out envelope for a callout, driven by its baked frame timing.
const useEnvelope = (callout: ResolvedCallout): Envelope => {
  const frame = useCurrentFrame();
  const holdEnd = callout.inFrames + callout.holdFrames;
  const opacityIn = interpolate(frame, [0, Math.max(1, callout.inFrames * 0.5)], [0, 1], CLAMP);
  const opacityOut = interpolate(frame, [holdEnd, holdEnd + callout.outFrames], [1, 0], CLAMP);
  const scaleIn = interpolate(frame, [0, callout.inFrames], [0.7, 1], EASE_OUT);
  const slideIn = interpolate(frame, [0, callout.inFrames], [-48, 0], EASE_OUT);
  return { opacity: Math.min(opacityIn, opacityOut), scaleIn, slideIn };
};

// The full-width event band shared by scoreboard + shock. accent colours the
// top/bottom rules so a scoreboard reads calm-yellow and a shock reads alarm-red.
const bandStyle = (accent: string): CSSProperties => ({
  width: "100%",
  padding: "34px 48px",
  background: "rgba(9, 10, 15, 0.86)",
  borderTop: `8px solid ${accent}`,
  borderBottom: `8px solid ${accent}`,
  boxShadow: "0 18px 40px rgba(0,0,0,0.55)",
  textAlign: "center",
});

const bandTextStyle: CSSProperties = {
  fontFamily: FONT_FAMILY,
  fontWeight: 900,
  fontSize: 110,
  lineHeight: 1.02,
  color: "#ffffff",
  textTransform: "uppercase",
  letterSpacing: "0.01em",
  WebkitTextStroke: "6px #000000",
  paintOrder: "stroke fill",
  textShadow: "0 8px 0 #000000, 0 0 26px rgba(0,0,0,0.7)",
};

// The headline text: flat `text`, or per-segment coloured `spans` (e.g. team
// names) so "USA vs ENGLAND" reads white-vs-red at a glance. The band's shared
// outline/shadow carries; only the fill colour changes per span.
const BandText: React.FC<{ readonly callout: ResolvedCallout }> = ({ callout }) => {
  if (callout.spans && callout.spans.length > 0) {
    return (
      <div style={bandTextStyle}>
        {callout.spans.map((span, index) => (
          <span key={`${span.text}-${index}`} style={{ color: span.color }}>
            {span.text}
          </span>
        ))}
      </div>
    );
  }
  return <div style={bandTextStyle}>{callout.text}</div>;
};

// Scoreboard: THE event marker. Slams in (eased scale), holds, quick fade.
const Scoreboard: React.FC<{ readonly callout: ResolvedCallout }> = ({ callout }) => {
  const { height } = useVideoConfig();
  const { opacity, scaleIn } = useEnvelope(callout);
  return (
    <AbsoluteFill style={{ justifyContent: "flex-start", alignItems: "center" }}>
      <div style={{ marginTop: BAND_TOP_FRAC * height, width: "100%", opacity }}>
        <div style={{ ...bandStyle(SCOREBOARD_ACCENT), transform: `scale(${scaleIn})` }}>
          <BandText callout={callout} />
        </div>
      </div>
    </AbsoluteFill>
  );
};

// Shock: scoreboard band + a red edge flash on entry + a 1-frame impact shake.
const Shock: React.FC<{ readonly callout: ResolvedCallout }> = ({ callout }) => {
  const frame = useCurrentFrame();
  const { height } = useVideoConfig();
  const { opacity, scaleIn } = useEnvelope(callout);
  const flash = interpolate(frame, [0, 6], [0.7, 0], CLAMP);
  const shakeX = frame < 1 ? 6 : frame < 2 ? -3 : 0;
  const shakeY = frame < 1 ? -6 : frame < 2 ? 3 : 0;
  return (
    <AbsoluteFill>
      <AbsoluteFill
        style={{ boxShadow: "inset 0 0 220px 48px rgba(255,40,40,1)", opacity: flash }}
      />
      <AbsoluteFill style={{ justifyContent: "flex-start", alignItems: "center" }}>
        <div
          style={{
            marginTop: BAND_TOP_FRAC * height,
            width: "100%",
            opacity,
            transform: `translate(${shakeX}px, ${shakeY}px)`,
          }}
        >
          <div style={{ ...bandStyle(SHOCK_ACCENT), transform: `scale(${scaleIn})` }}>
            <BandText callout={callout} />
          </div>
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

// Label: a small corner tag (e.g. a place / date), gentle slide-in from the left.
const Label: React.FC<{ readonly callout: ResolvedCallout }> = ({ callout }) => {
  const { height } = useVideoConfig();
  const { opacity, slideIn } = useEnvelope(callout);
  return (
    <AbsoluteFill style={{ justifyContent: "flex-start", alignItems: "flex-start" }}>
      <div
        style={{
          marginTop: LABEL_TOP_FRAC * height,
          marginLeft: 56,
          padding: "16px 26px",
          background: "rgba(9, 10, 15, 0.82)",
          borderLeft: `10px solid ${SCOREBOARD_ACCENT}`,
          opacity,
          transform: `translateX(${slideIn}px)`,
          fontFamily: FONT_FAMILY,
          fontWeight: 900,
          fontSize: 54,
          color: "#ffffff",
          textTransform: "uppercase",
          letterSpacing: "0.02em",
          WebkitTextStroke: "3px #000000",
          paintOrder: "stroke fill",
          textShadow: "0 5px 0 #000000, 0 0 16px rgba(0,0,0,0.6)",
        }}
      >
        {callout.text}
      </div>
    </AbsoluteFill>
  );
};

const OneCallout: React.FC<{ readonly callout: ResolvedCallout }> = ({ callout }) => {
  if (callout.style === "label") {
    return <Label callout={callout} />;
  }
  if (callout.style === "shock") {
    return <Shock callout={callout} />;
  }
  return <Scoreboard callout={callout} />;
};

// The story-comprehension layer: big text callouts (who vs who / what just
// happened) synced to the narration, kisahistory-style. Renders nothing when the
// episode authored no callouts (older episodes keep the emphasis-pops layer).
export const StoryCallouts: React.FC<StoryCalloutsProps> = ({ callouts }) => {
  if (callouts.length === 0) {
    return null;
  }
  return (
    <>
      {callouts.map((callout, index) => (
        <Sequence
          key={`${callout.style}-${callout.frame}-${index}`}
          from={callout.frame}
          durationInFrames={callout.life}
        >
          <OneCallout callout={callout} />
        </Sequence>
      ))}
    </>
  );
};
