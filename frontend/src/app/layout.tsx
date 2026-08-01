import type { Metadata } from "next";
import "@/styles/globals.css";

export const metadata: Metadata = {
  title: "Alto Motors — AI Support Orchestrator",
  description:
    "Multilingual AI customer-support orchestration for Alto Motors, Velmora. " +
    "Every routing decision explained, every answer traced to its source.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
