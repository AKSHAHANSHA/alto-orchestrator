import type { Config } from "tailwindcss";

/**
 * Swiss / International Style design tokens.
 *
 * The discipline of this style is subtractive: a strict grid, one typeface at
 * a few deliberate sizes, generous white space, hairline rules instead of
 * boxes, and colour reserved for meaning rather than decoration.
 *
 * Two brand accents carry the warmth — Karva amber and Renzo indigo — against
 * near-black on pure white. A Swiss red is held back for single moments of
 * emphasis, never for ornament.
 */
const config: Config = {
  content: ["./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: {
          DEFAULT: "#0A0A0A",
          muted: "#4A4A4A",
          faint: "#8A8A8A",
        },
        rule: "#E4E4E4",
        paper: "#FFFFFF",
        offset: "#FAFAFA",
        karva: {
          DEFAULT: "#E8820C",
          soft: "#FDF3E7",
        },
        renzo: {
          DEFAULT: "#1F3A93",
          soft: "#EDF0F9",
        },
        signal: "#D6231F",
        positive: "#1B7F5A",
      },
      fontFamily: {
        // Helvetica is the canonical Swiss face; Inter is its closest
        // ubiquitous stand-in and ships with better hinting on screens.
        sans: [
          "Inter",
          "Helvetica Neue",
          "Helvetica",
          "Arial",
          "system-ui",
          "sans-serif",
        ],
        mono: ["JetBrains Mono", "SF Mono", "Menlo", "monospace"],
        arabic: ["Noto Naskh Arabic", "Segoe UI", "Tahoma", "sans-serif"],
      },
      fontSize: {
        // A deliberate, restrained type scale. Fewer sizes, used consistently,
        // is what makes a page feel ordered rather than merely tidy.
        display: ["clamp(3rem, 8vw, 6.5rem)", { lineHeight: "0.94", letterSpacing: "-0.035em" }],
        headline: ["clamp(2rem, 4vw, 3.25rem)", { lineHeight: "1.04", letterSpacing: "-0.025em" }],
        title: ["1.5rem", { lineHeight: "1.2", letterSpacing: "-0.015em" }],
        lead: ["1.1875rem", { lineHeight: "1.55" }],
        body: ["0.9375rem", { lineHeight: "1.65" }],
        caption: ["0.8125rem", { lineHeight: "1.5" }],
        label: ["0.6875rem", { lineHeight: "1.3", letterSpacing: "0.13em" }],
      },
      maxWidth: {
        grid: "1440px",
challenge: "68ch",
      },
      spacing: {
        section: "clamp(6rem, 12vw, 11rem)",
      },
      transitionTimingFunction: {
        swiss: "cubic-bezier(0.22, 0.61, 0.36, 1)",
      },
    },
  },
  plugins: [],
};

export default config;
