import { continueRender, delayRender } from "remotion";

// The faces load lazily; a frame captured before they arrive would be set in the fallback.
const FACES = ["500 1em Geist", "600 1em Geist", "800 1em Unbounded", "400 1em 'IBM Plex Mono'", "500 1em 'IBM Plex Mono'", "600 1em 'IBM Plex Mono'"];

export function waitForFonts(): void {
  const handle = delayRender("fonts");
  Promise.all(FACES.map((face) => document.fonts.load(face))).then(() => continueRender(handle));
}
