import { AbsoluteFill, Sequence, useCurrentFrame } from "remotion";
import captions from "./captions.json";
import { Caption, EndCard, Field, Pointer, Recording, Ring, rise, Still, TerminalCard, type View } from "./parts";
import type { Clip } from "./reflection";

const FPS = captions.fps;
const BEATS = captions.review.beats;

/** A still of the studio for part of a beat: where the view starts and ends, a pointer's path
 * (x, y in the still's CSS pixels, and the frame it is there), the frame it presses, a ring. */
export type Shot = {
  shot: string;
  seconds: number;
  from: View;
  to?: View;
  pointer?: [number, number, number][];
  press?: number;
  ring?: { x: number; y: number; width: number; height: number; start: number };
};

export type ReviewProps = {
  opening: Clip;
  beats: Shot[][];
  consult: Clip;
};

function frames(beat: number): number {
  return (BEATS[beat].to - BEATS[beat].from) * FPS;
}

function speed(seconds: number, frames: number): string {
  return `×${Math.max(1, Math.round(seconds / (frames / FPS)))}`;
}

function Terminal({ clip, length }: { clip: Clip; length: number }) {
  return (
    <AbsoluteFill style={{ alignItems: "center", paddingTop: 40 }}>
      <TerminalCard label={clip.label} speed={speed(clip.seconds - (clip.from ?? 0), length)} style={{ width: 1600, height: 836 }}>
        <Recording clip={clip.clip} seconds={clip.seconds - (clip.from ?? 0)} from={clip.from} frames={length} />
      </TerminalCard>
    </AbsoluteFill>
  );
}

function ShotScene({ shot, length, first }: { shot: Shot; length: number; first: boolean }) {
  const frame = useCurrentFrame();
  // The beat's first still fades in; the rest cut, as the page itself changes.
  const shown = first ? rise(frame, 0, 10) : 1;
  return (
    <AbsoluteFill style={{ alignItems: "center", paddingTop: 40 }}>
      <div style={{ opacity: shown }}>
        <Still shot={shot.shot} frames={length} from={shot.from} to={shot.to} width={1600} height={836}>
          {shot.ring ? <Ring {...shot.ring} /> : null}
          {shot.pointer ? <Pointer path={shot.pointer} at={shot.press} /> : null}
        </Still>
      </div>
    </AbsoluteFill>
  );
}

function Shots({ shots, length }: { shots: Shot[]; length: number }) {
  const total = shots.reduce((sum, shot) => sum + shot.seconds, 0);
  let start = 0;
  return (
    <>
      {shots.map((shot, index) => {
        const share = index === shots.length - 1 ? length - start : Math.round((shot.seconds / total) * length);
        const from = start;
        start += share;
        return (
          // biome-ignore lint/suspicious/noArrayIndexKey: shots of one beat, in order
          <Sequence key={index} from={from} durationInFrames={share} layout="none">
            <ShotScene shot={shot} length={share} first={index === 0} />
          </Sequence>
        );
      })}
    </>
  );
}

export function Review(props: ReviewProps) {
  const scene = (beat: number) => {
    if (beat === 0) return <Terminal clip={props.opening} length={frames(0)} />;
    if (beat === 6) return <Terminal clip={props.consult} length={frames(6)} />;
    if (beat === 7) return <EndCard frames={frames(7)} />;
    return <Shots shots={props.beats[beat - 1]} length={frames(beat)} />;
  };
  return (
    <AbsoluteFill>
      <Field />
      {BEATS.map((beat, index) => (
        <Sequence key={beat.caption} from={beat.from * FPS} durationInFrames={frames(index)}>
          {scene(index)}
          <Caption text={beat.caption} frames={frames(index)} />
        </Sequence>
      ))}
    </AbsoluteFill>
  );
}
