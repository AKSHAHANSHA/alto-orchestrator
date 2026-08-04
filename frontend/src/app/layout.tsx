import type { Metadata, Viewport } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import "@/styles/globals.css";

/**
 * Geist is self-hosted by next/font at build time — the files are emitted
 * into the bundle, so there is no runtime request to Google and no flash of
 * fallback text. Both faces are exposed as CSS variables and picked up by
 * `fontFamily` in the Tailwind config.
 */
const geist = Geist({
  subsets: ["latin"],
  variable: "--font-geist",
  display: "swap",
});

const geistMono = Geist_Mono({
  subsets: ["latin"],
  variable: "--font-geist-mono",
  display: "swap",
});

export const metadata: Metadata = {
  title: "LUMO — AI Assistant for Alto Motors",
  description:
    "LUMO is the multilingual AI assistant for Alto Motors, Velmora. " +
    "Every routing decision explained, every answer traced to its source.",
};

export const viewport: Viewport = {
  themeColor: "#2b1c48",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className={`${geist.variable} ${geistMono.variable}`}>
      <body>{children}</body>
    </html>
  );
}
