import { AbsoluteFill, Easing, Img, interpolate, staticFile, useCurrentFrame } from "remotion";

// easeInOut so the pan/zoom starts and ends at zero velocity (no jerk at cuts).
const EASE = {
  extrapolateRight: "clamp",
  easing: Easing.inOut(Easing.cubic),
} as const;

type PanZoom = {
  readonly fromScale: number;
  readonly toScale: number;
  readonly fromX: number;
  readonly toX: number;
  readonly fromY: number;
  readonly toY: number;
};

// Enhanced Ken Burns fallback for scenes without parallax layers. A touch more
// travel than the old version so even un-layered scenes keep moving; cross-fading
// is now handled by the transition system, not here.
const MOVES: readonly PanZoom[] = [
  { fromScale: 1.06, toScale: 1.24, fromX: -3, toX: 4, fromY: -3, toY: 3 },
  { fromScale: 1.24, toScale: 1.06, fromX: 4, toX: -4, fromY: 3, toY: -3 },
  { fromScale: 1.08, toScale: 1.22, fromX: 0, toX: 0, fromY: 4, toY: -4 },
  { fromScale: 1.22, toScale: 1.08, fromX: -4, toX: 4, fromY: 0, toY: 0 },
  { fromScale: 1.1, toScale: 1.26, fromX: 3, toX: -3, fromY: -4, toY: 4 },
];

type KenBurnsBaseProps = {
  readonly src: string;
  readonly index: number;
  readonly frames: number;
};

export const KenBurnsBase: React.FC<KenBurnsBaseProps> = ({ src, index, frames }) => {
  const frame = useCurrentFrame();
  const move = MOVES[index % MOVES.length];
  const scale = interpolate(frame, [0, frames], [move.fromScale, move.toScale], EASE);
  const translateX = interpolate(frame, [0, frames], [move.fromX, move.toX], EASE);
  const translateY = interpolate(frame, [0, frames], [move.fromY, move.toY], EASE);

  return (
    <AbsoluteFill>
      <Img
        src={staticFile(src)}
        style={{
          width: "100%",
          height: "100%",
          objectFit: "cover",
          transform: `scale(${scale}) translate(${translateX}%, ${translateY}%)`,
          imageRendering: "pixelated",
        }}
      />
    </AbsoluteFill>
  );
};
