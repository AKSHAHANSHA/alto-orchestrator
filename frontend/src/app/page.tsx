import Link from "next/link";
import { Reveal } from "@/components/Reveal";

/**
 * Public landing page.
 *
 * Deliberately short and non-technical. The audience here is walking-in
 * customers, browsing prospects and a general reader — not the engineering
 * team. The detailed pipeline, confidence-signal breakdown, provenance
 * example and architecture diagrams live on `/workflow`, one click away for
 * anyone who wants them.
 *
 * The rhythm is: one image (the two brands), one sentence about the change,
 * a warm invitation, one clear call to action.
 */

export default function LandingPage() {
  return (
    <main className="min-h-screen bg-paper">
      {/* ── Masthead ─────────────────────────────────────────────── */}
      <header className="sticky top-0 z-50 border-b border-rule bg-paper/90 backdrop-blur-sm">
        <div className="grid-field h-16 items-center">
          <div className="col-span-2 flex items-center gap-3 md:col-span-4">
            <span className="block h-3 w-3 bg-ink" aria-hidden />
            <span className="text-caption font-medium tracking-tight">
              Alto Motors
            </span>
          </div>
          <nav className="col-span-2 flex items-center justify-end gap-6 md:col-span-8">
            <Link
              href="/workflow"
              className="hidden text-caption text-ink-muted transition-colors hover:text-ink sm:block"
            >
              How it works
            </Link>
            <Link
              href="/chat"
              className="hidden text-caption text-ink-muted transition-colors hover:text-ink sm:block"
            >
              Talk to us
            </Link>
            <Link
              href="/chat"
              className="bg-ink px-4 py-2 text-caption text-paper transition-opacity hover:opacity-85"
            >
              Start a conversation
            </Link>
          </nav>
        </div>
      </header>

      {/* ── Hero ─────────────────────────────────────────────────── */}
      <section className="grid-field pb-section pt-24 md:pt-40">
        <div className="col-span-4 md:col-span-12">
          <Reveal>
            <p className="label mb-10">Karva · Renzo · Velmora</p>
          </Reveal>
        </div>

        <div className="col-span-4 md:col-span-10">
          <Reveal delay={60}>
            <h1 className="text-display font-semibold">
              A better way
              <br />
              to buy your
              <br />
              next car.
            </h1>
          </Reveal>
        </div>

        <div className="col-span-4 mt-14 md:col-span-6 md:col-start-7 md:mt-24">
          <Reveal delay={140}>
            <p className="text-lead text-ink-muted">
              Two brands, one showroom, and answers to your questions the
              same day you ask them — whether that&rsquo;s about a test drive,
              financing, or the value of the car you&rsquo;re trading in.
            </p>
          </Reveal>
        </div>
      </section>

      {/* ── The two brands ───────────────────────────────────────── */}
      <section className="border-t border-rule py-section">
        <div className="grid-field">
          <div className="col-span-4 md:col-span-12">
            <Reveal>
              <p className="label mb-10">What we sell</p>
            </Reveal>
          </div>

          <div className="col-span-4 md:col-span-12">
            <div className="grid grid-cols-1 gap-px bg-rule md:grid-cols-2">
              <Reveal>
                <article className="h-full bg-paper p-10 md:p-14">
                  <div className="h-1 w-16 bg-karva" aria-hidden />
                  <h2 className="mt-8 text-headline font-semibold">Karva</h2>
                  <p className="mt-3 text-body text-ink-muted">
                    Affordable sedans and SUVs. Reliable, efficient, easy to
                    live with.
                  </p>
                  <p className="mt-8 text-body text-ink-muted">
                    Popular with first-time buyers, families, and anyone who
                    wants a car that keeps its value.
                  </p>
                </article>
              </Reveal>
              <Reveal delay={80}>
                <article className="h-full bg-paper p-10 md:p-14">
                  <div className="h-1 w-16 bg-renzo" aria-hidden />
                  <h2 className="mt-8 text-headline font-semibold">Renzo</h2>
                  <p className="mt-3 text-body text-ink-muted">
                    Premium and performance. Luxury sedans, refined SUVs,
                    coupes, and a serious performance line.
                  </p>
                  <p className="mt-8 text-body text-ink-muted">
                    For drivers who care about materials, presence and the
                    experience of the drive itself.
                  </p>
                </article>
              </Reveal>
            </div>
          </div>
        </div>
      </section>

      {/* ── What you can ask ─────────────────────────────────────── */}
      <section className="border-t border-rule bg-offset py-section">
        <div className="grid-field">
          <div className="col-span-4 md:col-span-4">
            <Reveal>
              <p className="label mb-6">Ask us anything</p>
              <h2 className="text-headline font-semibold">
                What you might want to know.
              </h2>
            </Reveal>
          </div>

          <div className="col-span-4 md:col-span-7 md:col-start-6">
            <div className="space-y-px bg-rule">
              {[
                {
                  q: "Can I test drive a Renzo on Saturday?",
                  a: "Yes. Weekend slots fill up early — the assistant can hold a time and a specialist will confirm within the hour.",
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
              ].map((item, index) => (
                <Reveal key={item.q} delay={index * 40}>
                  <div className="bg-paper p-6">
                    <p className="text-body font-medium">{item.q}</p>
                    <p className="mt-2 text-caption text-ink-muted">
                      {item.a}
                    </p>
                  </div>
                </Reveal>
              ))}
            </div>
          </div>
        </div>
      </section>

      {/* ── The change ───────────────────────────────────────────── */}
      <section className="py-section">
        <div className="grid-field">
          <div className="col-span-4 md:col-span-8 md:col-start-3">
            <Reveal>
              <p className="label mb-8 text-center">Why this is different</p>
              <p className="text-center text-headline font-semibold leading-tight">
                Your questions answered the moment you ask —
                <br className="hidden md:block" />{" "}
                <span className="text-ink-muted">
                  in English or Arabic, on a phone or in the showroom.
                </span>
              </p>
            </Reveal>

            <Reveal delay={120}>
              <p className="mx-auto mt-10 max-w-challenge text-center text-lead text-ink-muted">
                You don&rsquo;t wait for a call back. You don&rsquo;t repeat
                yourself. And when the answer needs a person — for a
                complaint, a specific quote, or a decision only a colleague
                can make — a real member of our team takes over the same
                conversation.
              </p>
            </Reveal>
          </div>
        </div>
      </section>

      {/* ── Call to action ───────────────────────────────────────── */}
      <section className="border-t border-ink py-section">
        <div className="grid-field">
          <div className="col-span-4 md:col-span-8 md:col-start-3">
            <Reveal>
              <h2 className="text-center text-display font-semibold">
                Ready to start?
              </h2>
            </Reveal>

            <Reveal delay={80}>
              <p className="mx-auto mt-8 max-w-challenge text-center text-lead text-ink-muted">
                Ask about a car, a test drive, financing, or your trade-in.
                Everything happens in one conversation.
              </p>

              <div className="mt-12 flex flex-wrap justify-center gap-4">
                <Link
                  href="/chat"
                  className="bg-ink px-8 py-4 text-body text-paper transition-opacity hover:opacity-85"
                >
                  Start a conversation
                </Link>
                <Link
                  href="/workflow"
                  className="border border-ink px-8 py-4 text-body transition-colors hover:bg-ink hover:text-paper"
                >
                  See how it works
                </Link>
              </div>
            </Reveal>
          </div>
        </div>
      </section>

      {/* ── Footer ───────────────────────────────────────────────── */}
      <footer className="border-t border-rule py-14">
        <div className="grid-field">
          <div className="col-span-4 md:col-span-6">
            <p className="text-caption text-ink-muted">
              Alto Motors, Velmora. Karva and Renzo are fictional brands.
            </p>
            <p className="mt-2 max-w-challenge text-caption text-ink-faint">
              This is a demonstration platform. Vehicle prices, procedures and
              policies are patterned on real UAE retail practice but are not
              genuine commercial offers.
            </p>
          </div>
          <div className="col-span-4 mt-8 md:col-span-3 md:col-start-10 md:mt-0 md:text-right">
            <p className="label">Alto AI Support Orchestrator</p>
          </div>
        </div>
      </footer>
    </main>
  );
}
