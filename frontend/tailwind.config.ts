import type { Config } from "tailwindcss";

/**
 * LUMO × Legend Motors design tokens.
 *
 * Two systems meet here and they share a spine. Legend Motors supplies the
 * marketing identity — deep purple surfaces, amber calls to action, near-black
 * text on white. LUMO supplies the assistant identity — warm cream panels and
 * parchment surfaces floating on a cool-grey canvas, with burnt orange for
 * interactive text where amber would fail contrast.
 *
 * The rules that keep it coherent:
 *
 *   · Amber (`brand`) is the accent, never the body. One primary action per
 *     screen gets it; everything else is plum, ghost, or text.
 *   · Amber on light backgrounds is 2.4:1 and fails AA. Interactive *text* on
 *     cream uses `brand-deep` (#ba4800, 5.9:1). Amber is for fills, where the
 *     label sits in white or plum on top of it.
 *   · Corners are round throughout, 8px to 28px. Nothing in this system has a
 *     square corner — mixing the two is the fastest way to make it look
 *     assembled rather than designed.
 *   · Depth is one soft, diffuse shadow used sparingly. Cards lift on hover;
 *     surfaces at rest stay flat.
 */
const config: Config = {
  content: ["./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        /* ── Legend Motors purple. Chrome, footers, primary surfaces. ── */
        plum: {
          DEFAULT: "#2b1c48",
          deep: "#1d1231",
          head: "#3a2740", // LUMO sidebar header
          soft: "#5d376e", // hover states, secondary tints
          tint: "#f4eff7", // pale wash for badges and quiet panels
        },

        /* ── The amber accent, and its accessible text sibling. ── */
        brand: {
          DEFAULT: "#ee8900",
          deep: "#ba4800", // interactive text on cream — passes AA
          soft: "#fef3e9", // warm cream fill
          edge: "#f6dcc0", // cream-compatible hairline
        },

        /* ── Text. `warm` is for copy sitting on cream. ── */
        ink: {
          DEFAULT: "#111827",
          muted: "#505050",
          faint: "#8a8a8a",
          warm: "#7a5a49",
        },

        rule: "#e2e8f0",
        paper: "#ffffff",
        offset: "#fdf8f3", // soft parchment
        canvas: "#f7f8fb", // cool-grey page background

        /* ── Product accents, folded into the brand palette so the two
              brands read as members of one family rather than two. ── */
        karva: { DEFAULT: "#ee8900", soft: "#fef3e9" },
        renzo: { DEFAULT: "#5d376e", soft: "#f4eff7" },

        signal: "#c62828",
        positive: "#1b7f5a",
      },

      fontFamily: {
        // Geist is loaded by next/font in the root layout and handed over as
        // a CSS variable, so the fallback chain here only matters for the
        // brief moment before it swaps in.
        sans: ["var(--font-geist)", "ui-sans-serif", "system-ui", "sans-serif"],
        mono: ["var(--font-geist-mono)", "ui-monospace", "SFMono-Regular", "monospace"],
        arabic: ["Noto Naskh Arabic", "Segoe UI", "Tahoma", "sans-serif"],
      },

      fontSize: {
        // Tops out at the brief's 64px display. Leading tightens as size
        // grows — the 80px line-height in the spec is for a one-line
        // greeting and opens gaps the moment a heading wraps.
        display: ["clamp(2.75rem, 6vw, 4rem)", { lineHeight: "1.06", letterSpacing: "-0.03em" }],
        greeting: ["clamp(2rem, 5vw, 4rem)", { lineHeight: "1.12", letterSpacing: "-0.025em" }],
        headline: ["clamp(1.75rem, 3.4vw, 2.5rem)", { lineHeight: "1.14", letterSpacing: "-0.022em" }],
        title: ["1.25rem", { lineHeight: "1.5", letterSpacing: "-0.012em" }],
        lead: ["1.0625rem", { lineHeight: "1.6" }],
        body: ["1rem", { lineHeight: "1.5" }],
        small: ["0.9375rem", { lineHeight: "1.6" }],
        caption: ["0.875rem", { lineHeight: "1.62", letterSpacing: "0.01em" }],
        label: ["0.8125rem", { lineHeight: "1.5", letterSpacing: "0.02em" }],
        micro: ["0.6875rem", { lineHeight: "1.4", letterSpacing: "0.12em" }],
      },

      borderRadius: {
        none: "0",
        sm: "6px",
        DEFAULT: "8px",
        md: "10px",
        lg: "12px",
        btn: "14px", // brief: New chat button
        xl: "16px",
        "2xl": "20px", // brief: send button
        "3xl": "24px",
        chat: "25px", // brief: chat container
        panel: "28px", // brief: sidebar panel
        "4xl": "32px",
        full: "9999px",
      },

      boxShadow: {
        // One diffuse shadow, two intensities. Nothing harder than this.
        soft: "0 1px 2px rgba(29,18,49,0.04), 0 10px 28px -14px rgba(29,18,49,0.12)",
        lift: "0 2px 6px rgba(29,18,49,0.05), 0 22px 48px -22px rgba(29,18,49,0.22)",
        inset: "inset 0 1px 0 rgba(255,255,255,0.6)",
      },

      maxWidth: {
        grid: "1440px",
        challenge: "68ch",
        chat: "820px",
      },

      spacing: {
        section: "clamp(4.5rem, 9vw, 8rem)",
      },

      transitionTimingFunction: {
        soft: "cubic-bezier(0.22, 0.61, 0.36, 1)",
      },

      keyframes: {
        "lumo-float": {
          "0%, 100%": { transform: "translateY(0)" },
          "50%": { transform: "translateY(-6px)" },
        },
        "dot-bounce": {
          "0%, 80%, 100%": { transform: "translateY(0)", opacity: "0.35" },
          "40%": { transform: "translateY(-4px)", opacity: "1" },
        },
        "rise-in": {
          from: { opacity: "0", transform: "translateY(8px)" },
          to: { opacity: "1", transform: "none" },
        },
      },

      animation: {
        "lumo-float": "lumo-float 4.5s ease-in-out infinite",
        "dot-bounce": "dot-bounce 1.3s ease-in-out infinite",
        "rise-in": "rise-in 0.35s cubic-bezier(0.22,0.61,0.36,1) both",
      },
    },
  },
  plugins: [],
};

export default config;
