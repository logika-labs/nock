// Renders each video and makes what the site serves, in web/site/videos/: NAME.mp4 (H.264), NAME.webm
// (VP9), NAME.jpg (the poster), NAME.vtt (the captions, from src/captions.json, the same words the
// video burns in), and the stills Getting started shows (STILLS). Each file must stay under 10 MB.
//
//   node scripts/finish.mjs [NAME…]
import { execFileSync } from "node:child_process";
import { mkdirSync, readFileSync, statSync, writeFileSync } from "node:fs";
import path from "node:path";

const here = path.dirname(new URL(import.meta.url).pathname);
const root = path.join(here, "..");
const site = path.join(root, "..", "site", "videos");
const captions = JSON.parse(readFileSync(path.join(root, "src", "captions.json"), "utf8"));
const LIMIT = 10 * 1024 * 1024;
// Each encoder's CRF.
const CRF = { h264: 28, vp9: 42 };
// The poster: a second of each video, after its opening card, that shows what it is about.
const POSTER = { reflection: 30, review: 25 };
// Stills Getting started shows, NAME.webp at 1200 wide: a second of a video each.
const STILLS = { review: { "review-work": 9, "review-verdict": 43 } };

function stamp(seconds) {
  const minutes = Math.floor(seconds / 60);
  return `00:${String(minutes).padStart(2, "0")}:${(seconds % 60).toFixed(3).padStart(6, "0")}`;
}

function run(command, args) {
  execFileSync(command, args, { cwd: root, stdio: "inherit" });
}

mkdirSync(site, { recursive: true });
mkdirSync(path.join(root, "out"), { recursive: true });
const names = process.argv.slice(2).length ? process.argv.slice(2) : ["reflection", "review"];
for (const name of names) {
  const master = path.join(root, "out", `${name}.mp4`);
  run("npx", ["remotion", "render", name, master, "--crf=18", "--log=error"]);
  const mp4 = path.join(site, `${name}.mp4`);
  run("ffmpeg", ["-v", "error", "-y", "-i", master, "-c:v", "libx264", "-preset", "slow", "-crf", String(CRF.h264), "-pix_fmt", "yuv420p",
    "-profile:v", "high", "-movflags", "+faststart", "-an", mp4]);
  const webm = path.join(site, `${name}.webm`);
  run("ffmpeg", ["-v", "error", "-y", "-i", master, "-c:v", "libvpx-vp9", "-crf", String(CRF.vp9), "-b:v", "0", "-row-mt", "1",
    "-deadline", "good", "-cpu-used", "2", "-an", webm]);
  run("ffmpeg", ["-v", "error", "-y", "-ss", String(captions.intro + POSTER[name]), "-i", master, "-frames:v", "1", "-q:v", "4",
    path.join(site, `${name}.jpg`)]);
  for (const [still, second] of Object.entries(STILLS[name] ?? {})) {
    const frame = path.join(root, "out", `${still}.png`);
    run("ffmpeg", ["-v", "error", "-y", "-ss", String(captions.intro + second), "-i", master, "-frames:v", "1", frame]);
    run("magick", [frame, "-resize", "1200x", "-quality", "70", path.join(site, `${still}.webp`)]);
  }
  const cues = captions[name].beats.map((beat, index) => `${index + 1}\n${stamp(captions.intro + beat.from)} --> ${stamp(captions.intro + beat.to)}\n${beat.caption}\n`);
  writeFileSync(path.join(site, `${name}.vtt`), `WEBVTT\n\n${cues.join("\n")}`);
  for (const file of [mp4, webm]) {
    const size = statSync(file).size;
    console.log(`${path.basename(file)}: ${(size / 1048576).toFixed(1)} MB`);
    if (size > LIMIT) throw new Error(`${file} is over 10 MB`);
  }
}
