import { Composition } from "remotion";
import { Short } from "./Short";
import { defaultProps, durationFromProps, FPS, HEIGHT, WIDTH } from "./config";
import type { ShortProps } from "./types";

export const RemotionRoot: React.FC = () => {
  return (
    <Composition
      id="Short"
      component={Short}
      durationInFrames={durationFromProps(defaultProps)}
      fps={FPS}
      width={WIDTH}
      height={HEIGHT}
      defaultProps={defaultProps}
      calculateMetadata={({ props }: { props: ShortProps }) => ({
        durationInFrames: durationFromProps(props),
        fps: props.fps,
        width: props.width,
        height: props.height,
      })}
    />
  );
};
