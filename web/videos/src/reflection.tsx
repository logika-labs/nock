import { AbsoluteFill, interpolate, Sequence, useCurrentFrame } from "remotion";
import captions from "./captions.json";
import { Caption, EndCard, Field, Recording, rise, Still, TerminalCard, type View } from "./parts";

const FPS = captions.fps;
const BEATS = captions.reflection.beats;

export type Clip = { clip: string; seconds: number; from?: number; label: string };
export type LedgerRow = { started: string; title: string; calls: { shape: string; command: string }[] };
export type Card = { shot: string; from: View; to?: View; label: string };

export type ReflectionProps = {
  opening: Clip;
  sessions: Clip[];
  ledger: { database: string; rows: LedgerRow[]; repeated: string[] };
  round: Clip;
  tool: { path: string; code: string };
  next: Clip;
  counter: { before: number; after: number; unit: string };
  cards: Card[];
};

function frames(beat: number): number {
  return (BEATS[beat].to - BEATS[beat].from) * FPS;
}

function at(beat: number): number {
  return BEATS[beat].from * FPS;
}

function speed(seconds: number, frames: number): string {
  return `×${Math.max(1, Math.round(seconds / (frames / FPS)))}`;
}

function Opening({ clip }: { clip: Clip }) {
  const length = frames(0);
  return (
    <AbsoluteFill style={{ alignItems: "center", paddingTop: 40 }}>
      <TerminalCard label={clip.label} speed={speed(clip.seconds - (clip.from ?? 0), length)} style={{ width: 1600, height: 836 }}>
        <Recording clip={clip.clip} seconds={clip.seconds - (clip.from ?? 0)} from={clip.from} frames={length} />
      </TerminalCard>
    </AbsoluteFill>
  );
}

function Repeats({ sessions }: { sessions: Clip[] }) {
  const length = frames(1);
  const frame = useCurrentFrame();
  return (
    <AbsoluteFill style={{ flexDirection: "row", justifyContent: "center", gap: 36, paddingTop: 40 }}>
      {sessions.map((clip, index) => {
        const shown = rise(frame, index * 5, 12);
        return (
          <TerminalCard
            key={clip.clip}
            label={clip.label}
            speed={speed(clip.seconds - (clip.from ?? 0), length)}
            style={{ width: 568, height: 836, opacity: shown, transform: `translateY(${(1 - shown) * 30}px)` }}
          >
            <Recording clip={clip.clip} seconds={clip.seconds - (clip.from ?? 0)} from={clip.from} frames={length} />
          </TerminalCard>
        );
      })}
    </AbsoluteFill>
  );
}

function Lock() {
  return (
    <svg width="26" height="30" viewBox="0 0 26 30" aria-hidden="true">
      <rect x="3" y="12" width="20" height="16" rx="4" fill="#111116" />
      <path d="M7.5 12V8.5a5.5 5.5 0 0 1 11 0V12" fill="none" stroke="#111116" strokeWidth="3" />
      <circle cx="13" cy="20" r="2.4" fill="#8fe9ff" />
    </svg>
  );
}

function Ledger({ ledger }: { ledger: ReflectionProps["ledger"] }) {
  const frame = useCurrentFrame();
  const length = frames(2);
  const pull = interpolate(frame, [0, 40], [1.08, 1], { extrapolateRight: "clamp" });
  return (
    <AbsoluteFill style={{ alignItems: "center", paddingTop: 40 }}>
      <div
        style={{
          width: 1600,
          height: 836,
          borderRadius: 24,
          padding: "34px 40px",
          background: "rgb(255 255 255 / .95)",
          boxShadow: "0 30px 60px -30px rgb(60 20 120 / .45), 4px 4px 0 0 var(--cyan), -4px -4px 0 0 var(--pink)",
          transform: `scale(${pull})`,
          display: "flex",
          flexDirection: "column",
          gap: 10,
          overflow: "hidden",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
          <span style={{ font: "500 22px/1 var(--mono)", letterSpacing: ".04em", textTransform: "uppercase", color: "var(--muted)" }}>
            {ledger.database}
          </span>
          <span
            style={{
              marginLeft: "auto",
              display: "flex",
              alignItems: "center",
              gap: 12,
              padding: "10px 18px",
              borderRadius: 999,
              background: "#f1eefa",
              font: "600 22px/1 var(--sans)",
              opacity: rise(frame, 30, 12),
            }}
          >
            <Lock /> on your machine, never committed
          </span>
        </div>
        {ledger.rows.map((row, index) => {
          const shown = rise(frame, 6 + index * 7, 10);
          return (
            <div
              key={row.started + row.title}
              style={{
                display: "grid",
                gridTemplateColumns: "250px 1fr",
                gap: 22,
                alignItems: "start",
                padding: "10px 0",
                borderTop: "1px solid rgb(17 17 22 / .1)",
                opacity: shown,
              }}
            >
              <div style={{ display: "grid", gap: 4 }}>
                <span style={{ font: "500 19px/1.2 var(--mono)", color: "var(--muted)" }}>{row.started}</span>
                <span style={{ font: "600 21px/1.25 var(--sans)" }}>{row.title}</span>
              </div>
              <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
                {row.calls.map((call, callIndex) => {
                  const repeated = ledger.repeated.includes(call.shape);
                  const lit = repeated ? rise(frame, 70 + index * 6 + callIndex * 3, 10) : 0;
                  return (
                    <span
                      // biome-ignore lint/suspicious/noArrayIndexKey: calls repeat by design
                      key={callIndex}
                      style={{
                        maxWidth: 1240,
                        overflow: "hidden",
                        textOverflow: "ellipsis",
                        whiteSpace: "nowrap",
                        padding: "6px 12px",
                        borderRadius: 10,
                        font: "500 17px/1.2 var(--mono)",
                        color: lit > 0.5 ? "#111116" : "#f1eefa",
                        background: lit > 0
                          ? `linear-gradient(120deg, rgb(255 154 213 / ${lit}), rgb(143 233 255 / ${lit}), rgb(255 226 122 / ${lit})), #15131d`
                          : "#15131d",
                        boxShadow: lit > 0.5 ? "0 6px 18px -6px rgb(255 120 200 / .7)" : "none",
                      }}
                    >
                      {call.command}
                    </span>
                  );
                })}
              </div>
            </div>
          );
        })}
      </div>
      <div style={{ position: "absolute", inset: 0, opacity: interpolate(frame, [length - 8, length], [0, 0]) }} />
    </AbsoluteFill>
  );
}

function Code({ tool, frame }: { tool: ReflectionProps["tool"]; frame: number }) {
  const lines = tool.code.split("\n");
  return (
    <TerminalCard label={tool.path} style={{ width: 1600, height: 836 }}>
      <pre style={{ margin: 0, padding: "22px 30px", font: "500 21px/1.42 var(--mono)", color: "#f1eefa", whiteSpace: "pre" }}>
        {lines.map((line, index) => {
          const shown = rise(frame, index * 0.9, 6);
          const decorator = line.trimStart().startsWith("@");
          const comment = line.trimStart().startsWith("#") || line.trimStart().startsWith('"""');
          return (
            // biome-ignore lint/suspicious/noArrayIndexKey: lines of one file, in order
            <div key={index} style={{ opacity: shown, color: decorator ? "#ff9ad5" : comment ? "#a49fbb" : undefined }}>
              {line || " "}
            </div>
          );
        })}
      </pre>
    </TerminalCard>
  );
}

function Round({ round, tool }: { round: Clip; tool: ReflectionProps["tool"] }) {
  const frame = useCurrentFrame();
  const length = frames(3);
  const split = Math.round(length * 0.58);
  return (
    <AbsoluteFill style={{ alignItems: "center", paddingTop: 40 }}>
      <Sequence durationInFrames={split} layout="none">
        <TerminalCard label={round.label} speed={speed(round.seconds - (round.from ?? 0), split)} style={{ width: 1600, height: 836 }}>
          <Recording clip={round.clip} seconds={round.seconds - (round.from ?? 0)} from={round.from} frames={split} />
        </TerminalCard>
      </Sequence>
      <Sequence from={split} layout="none">
        <Code tool={tool} frame={frame - split} />
      </Sequence>
    </AbsoluteFill>
  );
}

function Next({ next, counter }: { next: Clip; counter: ReflectionProps["counter"] }) {
  const frame = useCurrentFrame();
  const length = frames(4);
  const shown = rise(frame, Math.round(length * 0.45), 14);
  return (
    <AbsoluteFill style={{ alignItems: "center", paddingTop: 40 }}>
      <TerminalCard label={next.label} speed={speed(next.seconds - (next.from ?? 0), length)} style={{ width: 1600, height: 836 }}>
        <Recording clip={next.clip} seconds={next.seconds - (next.from ?? 0)} from={next.from} frames={length} />
      </TerminalCard>
      <div
        style={{
          position: "absolute",
          right: 210,
          top: 150,
          display: "flex",
          alignItems: "baseline",
          gap: 20,
          padding: "22px 34px",
          borderRadius: 22,
          background: "rgb(255 255 255 / .96)",
          boxShadow: "4px 4px 0 0 var(--cyan), -4px -4px 0 0 var(--pink), 0 20px 40px -20px rgb(17 17 22 / .6)",
          opacity: shown,
          transform: `scale(${0.9 + shown * 0.1})`,
        }}
      >
        <span style={{ font: "800 64px/1 var(--display)", color: "#a49fbb", textDecoration: "line-through", textDecorationThickness: 5 }}>
          {counter.before}
        </span>
        <span style={{ font: "800 54px/1 var(--display)" }}>→</span>
        <span style={{ font: "800 64px/1 var(--display)" }}>{counter.after}</span>
        <span style={{ font: "600 26px/1 var(--sans)", color: "var(--muted)" }}>{counter.unit}</span>
      </div>
    </AbsoluteFill>
  );
}

function Cards({ cards }: { cards: Card[] }) {
  const length = frames(5);
  const each = Math.floor(length / cards.length);
  return (
    <AbsoluteFill style={{ alignItems: "center", paddingTop: 40 }}>
      {cards.map((card, index) => (
        <Sequence key={card.shot} from={index * each} durationInFrames={index === cards.length - 1 ? length - index * each : each} layout="none">
          <CardStill card={card} frames={each} />
        </Sequence>
      ))}
    </AbsoluteFill>
  );
}

function CardStill({ card, frames: length }: { card: Card; frames: number }) {
  const frame = useCurrentFrame();
  const shown = rise(frame, 0, 10);
  return (
    <div style={{ position: "relative", opacity: shown, transform: `translateX(${(1 - shown) * 60}px)` }}>
      <Still shot={card.shot} frames={length} from={card.from} to={card.to} width={1600} height={836} />
      <span
        style={{
          position: "absolute",
          left: 28,
          top: 24,
          padding: "10px 18px",
          borderRadius: 999,
          background: "#111116",
          color: "#fff",
          font: "600 22px/1 var(--mono)",
          letterSpacing: ".06em",
          textTransform: "uppercase",
        }}
      >
        {card.label}
      </span>
    </div>
  );
}

export function Reflection(props: ReflectionProps) {
  const scenes = [
    <Opening key="0" clip={props.opening} />,
    <Repeats key="1" sessions={props.sessions} />,
    <Ledger key="2" ledger={props.ledger} />,
    <Round key="3" round={props.round} tool={props.tool} />,
    <Next key="4" next={props.next} counter={props.counter} />,
    <Cards key="5" cards={props.cards} />,
    <EndCard key="6" frames={frames(6)} />,
  ];
  return (
    <AbsoluteFill>
      <Field />
      {scenes.map((scene, beat) => (
        <Sequence key={BEATS[beat].caption} from={at(beat)} durationInFrames={frames(beat)}>
          {scene}
          <Caption text={BEATS[beat].caption} frames={frames(beat)} />
        </Sequence>
      ))}
    </AbsoluteFill>
  );
}
