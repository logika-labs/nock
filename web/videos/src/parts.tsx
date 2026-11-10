import type { CSSProperties, ReactNode } from "react";
import {
  AbsoluteFill,
  Img,
  interpolate,
  OffthreadVideo,
  Easing,
  Sequence,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";

const ease = Easing.bezier(0.25, 0.1, 0.25, 1);

/** 0 → 1 over the first `length` frames, 1 → 0 over the last. */
export function fade(frame: number, total: number, length = 9): number {
  return interpolate(frame, [0, length, total - length, total], [0, 1, 1, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
}

export function rise(frame: number, start = 0, length = 14): number {
  return interpolate(frame, [start, start + length], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: ease,
  });
}

const GRAIN =
  "url(\"data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='200' height='200'><filter id='d'><feTurbulence type='fractalNoise' baseFrequency='1.1' numOctaves='2' seed='3' stitchTiles='stitch'/><feColorMatrix values='0 0 0 0 .1  0 0 0 0 .05  0 0 0 0 .2  3 0 0 0 -1.75'/></filter><filter id='l'><feTurbulence type='fractalNoise' baseFrequency='1.1' numOctaves='2' seed='8' stitchTiles='stitch'/><feColorMatrix values='0 0 0 0 1  0 0 0 0 1  0 0 0 0 1  3 0 0 0 -1.7'/></filter><rect width='100%' height='100%' filter='url(%23d)'/><rect width='100%' height='100%' filter='url(%23l)'/></svg>\")";

/** The site's holographic field with its grain over it (style.css's .backdrop); still, so the encoder spends its bits
 * on what moves. */
export function Field() {
  return (
    <AbsoluteFill style={{ background: "#e9e2ff", overflow: "hidden" }}>
      <div
        style={{
          position: "absolute",
          inset: "-20%",
          background: [
            "radial-gradient(36% 30% at 20% 25%, #ff9ad5 0%, transparent 70%)",
            "radial-gradient(30% 34% at 75% 20%, #8fe9ff 0%, transparent 70%)",
            "radial-gradient(34% 30% at 60% 70%, #fff2a0 0%, transparent 70%)",
            "radial-gradient(30% 30% at 25% 80%, #c3b2ff 0%, transparent 70%)",
            "radial-gradient(26% 26% at 90% 85%, #ffb0d6 0%, transparent 70%)",
            "conic-gradient(from 210deg at 50% 50%, #ff9ad5, #c3b2ff, #8fe9ff, #d9ffd0, #fff2a0, #ffb0d6, #ff9ad5)",
          ].join(","),
          filter: "saturate(1.15)",
        }}
      />
      <AbsoluteFill style={{ background: `${GRAIN} 0 0 / 200px 200px`, opacity: 0.5 }} />
    </AbsoluteFill>
  );
}

/** Where a beat's picture starts: below the caption, at the top of the frame, with a margin under it. */
export const PICTURE_TOP = 204;

/** The burned-in caption: black, with the site's foil offset, at the top of the frame. */
export function Caption({ text, frames }: { text: string; frames: number }) {
  const frame = useCurrentFrame();
  const shown = fade(frame, frames, 8);
  return (
    <AbsoluteFill style={{ justifyContent: "flex-start", alignItems: "center", paddingTop: 44 }}>
      <div
        style={{
          maxWidth: 1500,
          padding: "18px 34px",
          borderRadius: 22,
          background: "#111116",
          color: "#fff",
          font: "500 38px/1.3 var(--sans)",
          letterSpacing: "-0.01em",
          textAlign: "center",
          textWrap: "balance",
          boxShadow: "4px 4px 0 0 var(--cyan), -4px -4px 0 0 var(--pink), 0 18px 40px -18px rgb(17 17 22 / .6)",
          opacity: shown,
          transform: `translateY(${(shown - 1) * 12}px)`,
        }}
      >
        {text}
      </div>
    </AbsoluteFill>
  );
}

/** A black terminal card, as the site draws them, with a label and an optional speed tag. */
export function TerminalCard({
  children,
  label,
  speed,
  style,
}: {
  children: ReactNode;
  label: string;
  speed?: string;
  style?: CSSProperties;
}) {
  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        borderRadius: 24,
        background: "#15131d",
        overflow: "hidden",
        boxShadow: "0 30px 60px -28px rgb(17 17 22 / .7), 4px 4px 0 0 var(--cyan), -4px -4px 0 0 var(--pink)",
        ...style,
      }}
    >
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 14,
          padding: "14px 22px",
          borderBottom: "1px solid rgb(255 255 255 / .1)",
          font: "600 19px/1 var(--mono)",
          letterSpacing: ".04em",
          color: "#fff",
        }}
      >
        <span style={{ display: "flex", gap: 8 }}>
          {["#ff9ad5", "#fff2a0", "#8fe9ff"].map((color) => (
            <span key={color} style={{ width: 13, height: 13, borderRadius: 99, background: color }} />
          ))}
        </span>
        <span>{label}</span>
        {speed ? (
          <span
            style={{
              marginLeft: "auto",
              padding: "6px 12px",
              borderRadius: 999,
              font: "600 15px/1 var(--mono)",
              letterSpacing: ".08em",
              color: "#111116",
              background: "linear-gradient(120deg, var(--pink), var(--cyan))",
            }}
          >
            {speed}
          </span>
        ) : null}
      </div>
      <div style={{ position: "relative", flex: 1, minHeight: 0 }}>{children}</div>
    </div>
  );
}

/** A recording, played faster so `seconds` of it fill `frames`; `from` skips its start. */
export function Recording({
  clip,
  seconds,
  frames,
  from = 0,
  style,
}: {
  clip: string;
  seconds: number;
  frames: number;
  from?: number;
  style?: CSSProperties;
}) {
  const { fps } = useVideoConfig();
  const rate = seconds / (frames / fps);
  return (
    <OffthreadVideo
      src={staticFile(clip)}
      muted
      playbackRate={rate}
      startFrom={Math.round(from * fps)}
      style={{ display: "block", width: "100%", height: "100%", objectFit: "cover", objectPosition: "top", ...style }}
    />
  );
}

export type View = { x: number; y: number; scale: number };

/** A 2x still of the studio in a white card, panned and zoomed from one view to another. */
export function Still({
  shot,
  frames,
  from,
  to,
  width,
  height,
  children,
}: {
  shot: string;
  frames: number;
  from: View;
  to?: View;
  width: number;
  height: number;
  children?: ReactNode;
}) {
  const frame = useCurrentFrame();
  const end = to ?? from;
  const t = interpolate(frame, [0, frames], [0, 1], { extrapolateRight: "clamp", easing: ease });
  const x = from.x + (end.x - from.x) * t;
  const y = from.y + (end.y - from.y) * t;
  const scale = from.scale + (end.scale - from.scale) * t;
  return (
    <div
      style={{
        position: "relative",
        width,
        height,
        borderRadius: 24,
        overflow: "hidden",
        background: "#f4f4f6",
        border: "1px solid rgb(255 255 255 / .9)",
        boxShadow: "0 30px 60px -30px rgb(60 20 120 / .45), 4px 4px 0 0 var(--cyan), -4px -4px 0 0 var(--pink)",
      }}
    >
      <div
        style={{
          position: "absolute",
          left: 0,
          top: 0,
          transformOrigin: "0 0",
          transform: `scale(${scale}) translate(${-x}px, ${-y}px)`,
        }}
      >
        <Img src={staticFile(shot)} style={{ display: "block", width: 1440 }} />
        {children}
      </div>
    </div>
  );
}

/** A pointer moving between points (in the still's CSS pixels), pressing at the last. */
export function Pointer({ path, at }: { path: [number, number, number][]; at?: number }) {
  const frame = useCurrentFrame();
  const frames = path.map((point) => point[2]);
  const x = interpolate(frame, frames, path.map((point) => point[0]), { extrapolateLeft: "clamp", extrapolateRight: "clamp", easing: ease });
  const y = interpolate(frame, frames, path.map((point) => point[1]), { extrapolateLeft: "clamp", extrapolateRight: "clamp", easing: ease });
  const press = at === undefined ? 0 : interpolate(frame, [at, at + 4, at + 14], [0, 1, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  return (
    <div style={{ position: "absolute", left: x, top: y, pointerEvents: "none" }}>
      {press > 0 ? (
        <div
          style={{
            position: "absolute",
            left: -22,
            top: -22,
            width: 44,
            height: 44,
            borderRadius: 99,
            border: "3px solid var(--pink)",
            opacity: press,
            transform: `scale(${0.6 + press * 0.6})`,
          }}
        />
      ) : null}
      <svg width="22" height="30" viewBox="0 0 22 30" style={{ transform: `scale(${1 - press * 0.12})`, filter: "drop-shadow(0 3px 4px rgb(0 0 0 / .35))" }}>
        <path d="M2 2v22l6-5.5 4 9 4-1.8-4-8.7h8z" fill="#111116" stroke="#fff" strokeWidth="2" strokeLinejoin="round" />
      </svg>
    </div>
  );
}

/** A soft frame around something on a still, drawn in foil. */
export function Ring({ x, y, width, height, start }: { x: number; y: number; width: number; height: number; start: number }) {
  const frame = useCurrentFrame();
  const shown = rise(frame, start, 10);
  return (
    <div
      style={{
        position: "absolute",
        left: x - 6,
        top: y - 6,
        width: width + 12,
        height: height + 12,
        borderRadius: 14,
        border: "4px solid var(--pink)",
        boxShadow: "0 0 0 4px var(--cyan), 0 10px 30px -8px rgb(255 120 200 / .6)",
        opacity: shown,
        transform: `scale(${1.04 - shown * 0.04})`,
      }}
    />
  );
}

/** The first and the last screen: the wordmark, the command that installs nock, and nock.dev. The first is there
 * from the first frame and fades out; the last rises in. */
export function NockCard({ frames, opening = false }: { frames: number; opening?: boolean }) {
  const frame = useCurrentFrame();
  const shown = opening ? 1 : rise(frame, 0, 16);
  const out = opening ? fade(frame + 9, frames + 9) : 1;
  return (
    <AbsoluteFill style={{ alignItems: "center", justifyContent: "center", gap: 48, paddingTop: 150, opacity: out }}>
      <span
        style={{
          font: "800 196px/1 var(--display)",
          letterSpacing: "-0.04em",
          opacity: shown,
          transform: `scale(${0.94 + shown * 0.06})`,
        }}
      >
        nock
      </span>
      <div
        style={{
          opacity: opening ? 1 : rise(frame, 8, 14),
          padding: "20px 34px",
          borderRadius: 18,
          background: "#111116",
          color: "#f1eefa",
          font: "500 44px/1 var(--mono)",
          boxShadow: "4px 4px 0 0 var(--cyan), -4px -4px 0 0 var(--pink)",
        }}
      >
        <span style={{ color: "#a49fbb" }}>$ </span>uvx nock init
      </div>
      <div
        style={{
          opacity: opening ? 1 : rise(frame, 16, 14) * fade(frame, frames + 30),
          font: "500 30px/1 var(--mono)",
          color: "var(--muted)",
        }}
      >
        nock.dev
      </div>
    </AbsoluteFill>
  );
}

/** A video between its cards: the field, the opening card for `intro` frames, then the beats, the last of which
 * is the closing card. */
export function Bookends({ intro, children }: { intro: number; children: ReactNode }) {
  return (
    <AbsoluteFill>
      <Field />
      <Sequence durationInFrames={intro}>
        <NockCard frames={intro} opening />
      </Sequence>
      <Sequence from={intro}>{children}</Sequence>
    </AbsoluteFill>
  );
}
