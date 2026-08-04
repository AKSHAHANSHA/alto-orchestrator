import Image, { type StaticImageData } from "next/image";

import gift from "../../Logos/1.png";
import thumbsUp from "../../Logos/2.png";
import heart from "../../Logos/3.png";
import cape from "../../Logos/4.png";
import read from "../../Logos/5.png";
import wave from "../../Logos/6.png";
import nap from "../../Logos/7.png";
import sleep from "../../Logos/8.png";

/**
 * LUMO — the mascot.
 *
 * The official renders, imported straight from `frontend/Logos/` where they
 * live. They are statically imported rather than copied into `public/`, so
 * webpack fingerprints them, emits AVIF/WebP variants and generates the
 * srcset — and the source files stay exactly where they were put.
 *
 * All eight are cut out (transparent background, verified), so they sit on
 * cream, white and deep purple surfaces without a plate behind them.
 *
 * `size` is the rendered **height**. The poses have quite different aspect
 * ratios — the cape render is landscape, the standing ones portrait — and
 * matching heights is what makes them look like the same character at the
 * same distance. Matching widths does not.
 *
 * A note on sizing: the source renders are 133–219px on their long edge, so
 * they are deliberately never rendered much above their native height. Push
 * one to 220px and it goes soft on any display above 1× — the art, not the
 * markup, is the limit. Drop 2× exports into `Logos/` and these numbers can
 * grow.
 */

export type LumoPose =
  | "wave"
  | "thumbsup"
  | "read"
  | "cape"
  | "heart"
  | "gift"
  | "sleep"
  | "nap";

const ART: Record<LumoPose, StaticImageData> = {
  gift, // 1 — carrying a wrapped present
  thumbsup: thumbsUp, // 2 — thumbs up
  heart, // 3 — holding a heart
  cape, // 4 — cape, mid-leap
  read, // 5 — reading a map
  wave, // 6 — waving, mid-stride
  nap, // 7 — curled up asleep
  sleep, // 8 — stretched out asleep
};

export function Lumo({
  pose = "wave",
  size = 128,
  float = false,
  priority = false,
  className = "",
}: {
  pose?: LumoPose;
  /** Rendered height in px; width follows the artwork's own aspect ratio. */
  size?: number;
  /** Gentle idle bob. Suppressed under prefers-reduced-motion. */
  float?: boolean;
  /** Set on above-the-fold art so it is not lazy-loaded. */
  priority?: boolean;
  className?: string;
}) {
  const art = ART[pose];
  const width = Math.round((size * art.width) / art.height);

  return (
    <Image
      src={art}
      alt=""
      aria-hidden
      width={width}
      height={size}
      priority={priority}
      className={`${float ? "animate-lumo-float" : ""} ${className}`}
      style={{ height: size, width: "auto" }}
    />
  );
}

/**
 * The compact mark, for the masthead and message avatars.
 *
 * A whole body shrunk to 28px is unreadable, so this crops to the character's
 * head. The box was measured off the thumbs-up render rather than guessed:
 * a 104px square at (28, 0) frames both horns and the visor with the body
 * just out of shot.
 */
const HEAD_CROP = { left: 28, top: 0, box: 104 };

export function LumoMark({
  size = 32,
  className = "",
}: {
  size?: number;
  className?: string;
}) {
  const scale = size / HEAD_CROP.box;

  return (
    <span
      aria-hidden
      className={`relative inline-block shrink-0 overflow-hidden rounded-[30%] bg-plum ${className}`}
      style={{ width: size, height: size }}
    >
      <Image
        src={thumbsUp}
        alt=""
        width={Math.round(thumbsUp.width * scale)}
        height={Math.round(thumbsUp.height * scale)}
        className="absolute max-w-none"
        style={{
          left: -HEAD_CROP.left * scale,
          top: -HEAD_CROP.top * scale,
        }}
      />
    </span>
  );
}
