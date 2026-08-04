import Link from "next/link";
import { Reveal } from "@/components/Reveal";
import { SiteHeader } from "@/components/SiteHeader";
import { SiteFooter } from "@/components/SiteFooter";
import { Lumo } from "@/components/Lumo";

/**
 * Public landing page.
 *
 * Deliberately short and non-technical. The audience here is walking-in
 * customers, browsing prospects and a general reader — not the engineering
 * team. The detailed pipeline, confidence-signal breakdown, provenance
 * example and architecture diagrams live on `/workflow`, one click away for
 * anyone who wants them.
 *
 * The rhythm is: meet LUMO, see the two brands, read four real questions,
 * one clear call to action. Warm cream and white surfaces float on the cool
 * canvas; the one deep-purple band carries the emotional beat so it lands
 * without needing a bigger typeface.
 */

const QUESTIONS = [
  {
    q: "Can I test drive a Renzo on Saturday?",
    a: "Yes. Weekend slots fill up early — LUMO can hold a time and a specialist will confirm within the hour.",
  },
  {
    q: "What is the monthly payment on a Karva Acadia?",
    a: "We show an indicative range based on the current published bank terms, then a finance consultant confirms with the bank.",
  },
  {
    q: "What is my old car worth?",
    a: "Share the make, model, year and mileage and we come back with an indicative range in a few minutes. The final offer is after a 45-minute inspection.",
  },
  {
    q: "When are you open?",
    a: "Monday to Thursday and Sunday, 09:00 to 21:00. Friday from 14:00. Saturday 10:00 to 22:00. Ramadan hours are different — just ask.",
  },
];

const BRANDS = [
  {
    name: "Karva",
    line: "Affordable sedans and SUVs. Reliable, efficient, easy to live with.",
    body: "Popular with first-time buyers, families, and anyone who wants a car that keeps its value.",
    accent: "bg-brand",
    tint: "bg-brand-soft",
    edge: "border-brand-edge",
  },
  {
    name: "Renzo",
    line: "Premium and performance. Luxury sedans, refined SUVs, coupes, and a serious performance line.",
    body: "For drivers who care about materials, presence and the experience of the drive itself.",
    accent: "bg-plum-soft",
    tint: "bg-plum-tint",
    edge: "border-plum/15",
  },
];

export default function LandingPage() {
  return (
    <main className="min-h-screen bg-canvas">
      <SiteHeader
        links={[
          { href: "/workflow", label: "How it works" },
          { href: "/admin", label: "Operations" },
          { href: "/chat", label: "Talk to LUMO", cta: true },
        ]}
      />

      {/* ── Hero ─────────────────────────────────────────────────── */}
      <section className="relative overflow-hidden">
        <div
          className="glow-brand pointer-events-none absolute -top-40 right-[-10%] h-[620px] w-[620px]"
          aria-hidden
        />

        <div className="grid-field relative pb-20 pt-16 md:pb-28 md:pt-24">
          <div className="col-span-4 md:col-span-7">
            <Reveal>
              <p className="label mb-5">Karva · Renzo · Velmora</p>
            </Reveal>

            <Reveal delay={60}>
              <h1 className="text-display font-semibold text-plum">
                A better way to buy your next car.
              </h1>
            </Reveal>

            <Reveal delay={140}>
              <p className="mt-7 max-w-challenge text-lead text-ink-muted">
                Two brands, one showroom, and answers to your questions the
                same day you ask them — whether that&rsquo;s about a test
                drive, financing, or the value of the car you&rsquo;re trading
                in.
              </p>
            </Reveal>

            <Reveal delay={200}>
              <div className="mt-10 flex flex-wrap items-center gap-3">
                <Link href="/chat" className="btn-primary btn-lg">
                  Start a conversation
                </Link>
                <Link href="/workflow" className="btn-ghost btn-lg">
                  See how it works
                </Link>
              </div>
            </Reveal>
          </div>

          {/* LUMO, introducing itself. The speech bubble does the work a
              caption would otherwise have to do. */}
          <div className="col-span-4 mt-14 flex items-center justify-center md:col-span-5 md:mt-0">
            <Reveal delay={120} className="w-full">
              <div className="relative mx-auto max-w-[380px]">
                <div className="card-warm relative rounded-panel p-8 shadow-soft">
                  <div className="flex justify-center">
                    <Lumo pose="wave" size={150} float priority />
                  </div>
                  <div className="mt-6 rounded-chat bg-paper px-5 py-4 shadow-soft">
                    <p className="text-small text-ink">
                      Hi, I&rsquo;m <strong className="text-brand-deep">LUMO</strong>.
                      Ask me about a car, a test drive, financing or your
                      trade-in — in English or Arabic.
                    </p>
                  </div>
                </div>
              </div>
            </Reveal>
          </div>
        </div>
      </section>

      {/* ── The two brands ───────────────────────────────────────── */}
      <section className="grid-field py-section">
        <div className="col-span-4 md:col-span-12">
          <Reveal>
            <p className="label mb-4">What we sell</p>
            <h2 className="max-w-[16ch] text-headline font-semibold text-plum">
              Two brands, one showroom floor.
            </h2>
          </Reveal>
        </div>

        <div className="col-span-4 mt-12 md:col-span-12">
          <div className="grid grid-cols-1 gap-6 md:grid-cols-2">
            {BRANDS.map((brand, index) => (
              <Reveal key={brand.name} delay={index * 80}>
                <article
                  className={`card-hover h-full rounded-panel border ${brand.edge} ${brand.tint} p-9 md:p-11`}
                >
                  <div
                    className={`h-1.5 w-14 rounded-full ${brand.accent}`}
                    aria-hidden
                  />
                  <h3 className="mt-7 text-headline font-semibold text-plum">
                    {brand.name}
                  </h3>
                  <p className="mt-3 text-body text-ink-muted">{brand.line}</p>
                  <p className="mt-6 text-small text-ink-muted">{brand.body}</p>
                </article>
              </Reveal>
            ))}
          </div>
        </div>
      </section>

      {/* ── What you can ask ─────────────────────────────────────── */}
      <section className="grid-field pb-section">
        <div className="col-span-4 md:col-span-4">
          <Reveal>
            <p className="label mb-4">Ask us anything</p>
            <h2 className="text-headline font-semibold text-plum">
              What you might want to know.
            </h2>
            <p className="mt-5 text-small text-ink-muted">
              Real questions, answered the way LUMO answers them — with the
              caveats included rather than left out.
            </p>
          </Reveal>
        </div>

        <div className="col-span-4 mt-10 md:col-span-7 md:col-start-6 md:mt-0">
          <div className="space-y-3">
            {QUESTIONS.map((item, index) => (
              <Reveal key={item.q} delay={index * 50}>
                <div className="card card-hover rounded-3xl p-6">
                  <p className="text-body font-semibold text-plum">{item.q}</p>
                  <p className="mt-2 text-small text-ink-muted">{item.a}</p>
                </div>
              </Reveal>
            ))}
          </div>
        </div>
      </section>

      {/* ── The change ───────────────────────────────────────────── */}
      <section className="grid-field pb-section">
        <div className="col-span-4 md:col-span-12">
          <Reveal>
            <div className="relative overflow-hidden rounded-panel bg-plum px-8 py-16 text-center md:px-16 md:py-24">
              <div
                className="glow-plum pointer-events-none absolute inset-x-0 -top-32 h-[520px]"
                aria-hidden
              />
              <div className="relative mx-auto max-w-3xl">
                <p className="label-muted mb-6 !text-brand">
                  Why this is different
                </p>
                <p className="text-headline font-semibold text-white">
                  Your questions answered the moment you ask —{" "}
                  <span className="text-white/55">
                    in English or Arabic, on a phone or in the showroom.
                  </span>
                </p>
                <p className="mx-auto mt-8 max-w-challenge text-lead text-white/70">
                  You don&rsquo;t wait for a call back. You don&rsquo;t repeat
                  yourself. And when the answer needs a person — for a
                  complaint, a specific quote, or a decision only a colleague
                  can make — a real member of our team takes over the same
                  conversation.
                </p>
              </div>
            </div>
          </Reveal>
        </div>
      </section>

      {/* ── Call to action ───────────────────────────────────────── */}
      <section className="grid-field pb-section">
        <div className="col-span-4 md:col-span-12">
          <Reveal>
            <div className="card-warm rounded-panel px-8 py-14 md:px-16">
              <div className="flex flex-col items-center gap-10 md:flex-row md:justify-between">
                <div className="max-w-xl text-center md:text-left">
                  <h2 className="text-headline font-semibold text-plum">
                    Ready to start?
                  </h2>
                  <p className="mt-4 text-lead text-ink-warm">
                    Ask about a car, a test drive, financing, or your trade-in.
                    Everything happens in one conversation.
                  </p>
                  <div className="mt-8 flex flex-wrap justify-center gap-3 md:justify-start">
                    <Link href="/chat" className="btn-primary btn-lg">
                      Start a conversation
                    </Link>
                    <Link href="/workflow" className="btn-ghost btn-lg">
                      See how it works
                    </Link>
                  </div>
                </div>
                <Lumo pose="thumbsup" size={140} className="shrink-0" />
              </div>
            </div>
          </Reveal>
        </div>
      </section>

      <SiteFooter />
    </main>
  );
}
