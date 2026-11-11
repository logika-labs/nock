import { Composition, staticFile } from "remotion";
import "./style.css";
import { waitForFonts } from "./fonts";
import captions from "./captions.json";
import { Reflection, type ReflectionProps } from "./reflection";
import { Review, type ReviewProps } from "./review";

// What a video shows is made by record/ into public/ (gitignored): the recordings, the studio's stills,
// and data/NAME.json, which names them and holds what the scenes draw.
async function props<T>(name: string): Promise<{ props: T }> {
  const response = await fetch(staticFile(`data/${name}.json`));
  return { props: (await response.json()) as T };
}

waitForFonts();

export function Root() {
  return (
    <>
      <Composition
        id="reflection"
        component={Reflection}
        width={1920}
        height={1080}
        fps={captions.fps}
        durationInFrames={captions.fps * (captions.intro + captions.reflection.seconds)}
        defaultProps={{} as ReflectionProps}
        calculateMetadata={() => props<ReflectionProps>("reflection")}
      />
      <Composition
        id="review"
        component={Review}
        width={1920}
        height={1080}
        fps={captions.fps}
        durationInFrames={captions.fps * (captions.intro + captions.review.seconds)}
        defaultProps={{} as ReviewProps}
        calculateMetadata={() => props<ReviewProps>("review")}
      />
    </>
  );
}
