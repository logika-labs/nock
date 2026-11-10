import { AbsoluteFill, Sequence, useCurrentFrame } from "remotion";
import captions from "./captions.json";
import { Bookends, Caption, NockCard, PICTURE_TOP, Recording, rise, TerminalCard } from "./parts";
import type { Clip } from "./reflection";
import { type Shot, Shots, Terminal } from "./review";

const FPS = captions.fps;
const BEATS = captions.evaluation.beats;

export type EvaluationProps = {
  complaint: string;
  answers: { label: string; text: string }[];
  fan: Shot[];
  logika: Shot[];
  stages: Shot[];
  decisions: Shot[];
  runs: Clip[];
  drill: Shot[];
  ask: Clip;
};

function frames(beat: number): number {
  return (BEATS[beat].to - BEATS[beat].from) * FPS;
}

/** Three of the eval's agents' answers to one bug, side by side, each in its own words. */
function Answers({ complaint, answers }: Pick<EvaluationProps, "complaint" | "answers">) {
  const frame = useCurrentFrame();
  return (
    <AbsoluteFill style={{ alignItems: "center", paddingTop: PICTURE_TOP, gap: 26 }}>
      <div
        style={{
          maxWidth: 1500,
          padding: "16px 28px",
          borderRadius: 18,
          background: "rgb(255 255 255 / .82)",
          font: "500 27px/1.4 var(--sans)",
          color: "var(--foreground)",
          opacity: rise(frame, 0, 10),
        }}
      >
        <span style={{ font: "600 18px/1 var(--mono)", letterSpacing: ".08em", color: "var(--muted)", marginRight: 14 }}>
          THE CUSTOMER
        </span>
        {complaint}
      </div>
      <div style={{ display: "flex", gap: 30 }}>
        {answers.map((answer, index) => {
          const shown = rise(frame, 8 + index * 7, 12);
          return (
            <div
              key={answer.label}
              style={{
                width: 500,
                padding: "24px 28px",
                borderRadius: 24,
                background: "#15131d",
                color: "#f1eefa",
                boxShadow: "0 30px 60px -28px rgb(17 17 22 / .7), 4px 4px 0 0 var(--cyan), -4px -4px 0 0 var(--pink)",
                opacity: shown,
                transform: `translateY(${(1 - shown) * 30}px)`,
                display: "flex",
                flexDirection: "column",
                gap: 16,
              }}
            >
              <span style={{ font: "600 19px/1 var(--mono)", letterSpacing: ".04em", color: "var(--cyan)" }}>{answer.label}</span>
              <span style={{ font: "400 24px/1.45 var(--mono)", whiteSpace: "pre-wrap" }}>{answer.text}</span>
            </div>
          );
        })}
      </div>
    </AbsoluteFill>
  );
}

/** Recordings one after another, each a share of the beat as long as it is. */
function Terminals({ clips, length }: { clips: Clip[]; length: number }) {
  const total = clips.reduce((sum, clip) => sum + Math.sqrt(clip.seconds), 0);
  let start = 0;
  return (
    <>
      {clips.map((clip, index) => {
        const share = index === clips.length - 1 ? length - start : Math.round((Math.sqrt(clip.seconds) / total) * length);
        const from = start;
        start += share;
        return (
          <Sequence key={clip.clip} from={from} durationInFrames={share} layout="none">
            <Terminal clip={clip} length={share} />
          </Sequence>
        );
      })}
    </>
  );
}

/** A recording played in the beat's first part, then held on its last frame, so its end can be read. */
function Held({ clip, length, hold }: { clip: Clip; length: number; hold: number }) {
  const play = length - hold;
  const seconds = clip.seconds - (clip.from ?? 0);
  return (
    <AbsoluteFill style={{ alignItems: "center", paddingTop: PICTURE_TOP }}>
      <TerminalCard label={clip.label} speed={`×${Math.round(seconds / (play / FPS))}`} style={{ width: 1600, height: 836 }}>
        <Sequence durationInFrames={play} layout="none">
          <Recording clip={clip.clip} seconds={seconds} from={clip.from} frames={play} />
        </Sequence>
        <Sequence from={play} layout="none">
          <Recording clip={clip.clip} seconds={0.05} from={clip.seconds - 0.1} frames={hold} />
        </Sequence>
      </TerminalCard>
    </AbsoluteFill>
  );
}

export function Evaluation(props: EvaluationProps) {
  const scenes = [
    <Shots key="0" shots={props.fan} length={frames(0)} />,
    <Answers key="1" complaint={props.complaint} answers={props.answers} />,
    <Shots key="2" shots={props.logika} length={frames(2)} />,
    <Shots key="3" shots={props.stages} length={frames(3)} />,
    <Shots key="4" shots={props.decisions} length={frames(4)} />,
    <Terminals key="5" clips={props.runs} length={frames(5)} />,
    <Shots key="6" shots={props.drill} length={frames(6)} />,
    <Held key="7" clip={props.ask} length={frames(7)} hold={2 * FPS} />,
    <NockCard key="8" frames={frames(8)} />,
  ];
  return (
    <Bookends intro={captions.intro * FPS}>
      {scenes.map((scene, beat) => (
        <Sequence key={BEATS[beat].caption} from={BEATS[beat].from * FPS} durationInFrames={frames(beat)}>
          {scene}
          <Caption text={BEATS[beat].caption} frames={frames(beat)} />
        </Sequence>
      ))}
    </Bookends>
  );
}
