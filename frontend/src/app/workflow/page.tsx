import Link from "next/link";
import { Reveal } from "@/components/Reveal";
import { SiteHeader } from "@/components/SiteHeader";
import { SiteFooter } from "@/components/SiteFooter";
import { Lumo } from "@/components/Lumo";

/**
 * Technical workflow page.
 *
 * The place the previous landing page lived, plus more architectural depth
 * that didn't fit a general-audience front door: the four cognitive layers,
 * the six confidence signals, the retrieval funnel, the graph shape, and the
 * things the platform will refuse to guess. Meant to be read by engineers,
 * technical leads, and anyone deciding whether to trust an AI system with
 * real customer conversations.
 *
 * Kept as one scrolling narrative on the same grid as the rest of the site,
 * so a reader arriving from the customer landing lands in a consistent
 * visual world. Numbered eyebrows carry the sequence; the cards carry the
 * detail.
 */

const PIPELINE = [
  {
    n: "01",
    layer: "Understanding",
    owner: "Language model",
    q: "What did the customer actually say?",
    detail:
      "Normalise, detect language, discover every intent, extract stated facts, read sentiment. This layer makes no decisions at all.",
  },
  {
    n: "02",
    layer: "Planning",
    owner: "Rule engine",
    q: "What should happen?",
    detail:
      "Turn the intent queue into ordered work: required facts, owning department, dependencies between requests. A pure function of policy.",
  },
  {
    n: "03",
    layer: "Decision",
    owner: "Business rules",
    q: "Answer, clarify, route, or escalate?",
    detail:
      "Six confidence signals, weighted. Hard overrides run first, so a strong average can never authorise automation where it does not belong.",
  },
  {
    n: "04",
    layer: "Execution",
    owner: "Deterministic",
    q: "Do it.",
    detail:
      "Hybrid retrieval, arithmetic, catalog lookup, bookings, notifications. The model writes prose; it never decides a figure.",
  },
];

const SIGNALS = [
  { name: "Language", note: "Script ratio and detector agreement" },
  { name: "Intent", note: "Classifier margin across the whole queue" },
  { name: "Entity", note: "Slot fill rate weighted by confidence" },
  { name: "Retrieval", note: "Top chunk score and its margin" },
  { name: "Risk", note: "Commercial exposure and customer sentiment" },
  { name: "Policy", note: "Approvals and regulatory constraints" },
];

const REFUSALS = [
  {
    title: "It will not invent a figure",
    body: "Every instalment and valuation comes from a deterministic function, checked against the CBUAE lending regulation. An answer citing a number no document supports is blocked before it is sent.",
  },
  {
    title: "It will not guess an intent",
    body: "“Is this still available?” names no vehicle. The system does not pick the likeliest one — it asks which, and waits. Unclear is a first-class outcome, not a failure.",
  },
  {
    title: "It will not lose a request",
    body: "A message with three requests becomes three tracked intents. Silence in a later message is not withdrawal — an unresolved intent survives by construction, not by remembering.",
  },
  {
    title: "It will not argue with an angry customer",
    body: "A complaint reaches a person regardless of how confident every other signal is. Some conversations should never be automated, and the rules say so explicitly.",
  },
  {
    title: "It will not confidently sell a car we don't stock",
    body: "Ask about a model that isn't in our catalog and the honest answer comes back — 'we don't stock that; here are the closest models we do'. A structured Postgres lookup rules first; semantic search never fills in the gap.",
  },
];

const STORES = [
  {
    name: "PostgreSQL",
    role: "Structured facts",
    detail:
      "The vehicle catalog, wide-event spans, human review queue, conversation state. Exact lookups: brand + model + year, one row or zero rows. The right tool for 'do you have the Renzo GX 470?'.",
  },
  {
    name: "Qdrant",
    role: "Vector search",
    detail:
      "The policy documents, the finance corpus and the catalog embedded as natural language. Two named vectors per point — dense multilingual + BM25 sparse — fused server-side by RRF, then reranked. The right tool for 'affordable Karva SUV'.",
  },
  {
    name: "Redis",
    role: "Short-term memory",
    detail:
      "Session-scoped context that doesn't need to survive a restart — clarification state, streaming buffers, transient rate-limits.",
  },
];

const RETRIEVAL_STAGES = [
  {
    n: "Prefetch × 2",
    detail:
      "Dense multilingual embedding and sparse BM25 with the IDF modifier, each returning the top 100 candidates. They run in parallel.",
  },
  {
    n: "Server-side RRF",
    detail:
      "Qdrant fuses the two rankings with Reciprocal Rank Fusion. No score-scale blending — RRF discards magnitudes and combines ranks, which is the only mathematically sound way to fuse two retrievers that don't share a scale.",
  },
  {
    n: "Cross-encoder rerank",
    detail:
      "The top 20 fused candidates are rescored by a local cross-encoder. English-only, so Arabic queries skip this stage and keep the fusion ranking — silently degrading beats scrambling a good order.",
  },
  {
    n: "Top-K",
    detail:
      "Five chunks reach the generator. Every score at every stage is stored on the chunk and shown in the customer UI.",
  },
];

const OVERRIDES = [
  "Any complaint keyword — routes to a person, always",
  "Negative sentiment combined with high urgency — routes to a person",
  "An answer citing a number the evidence doesn't support — routes to a person",
  "A financial claim without a supporting document — routes to a person",
  "A conversation any human has already touched — stays with the human",
];

const MESSAGES = [
  {
    quote:
      "I want to trade in my old Karva SUV and also check financing for a new Renzo S5 — and can I test drive it Saturday?",
    read: "Three intents. Financing depends on the trade-in value, so quoting an instalment first would produce a number that has to be retracted.",
    dir: "ltr" as const,
  },
  {
    quote: "is this still available?",
    read: "One intent, one missing fact. The system knows exactly which — and asks that question rather than guessing a vehicle.",
    dir: "ltr" as const,
  },
  {
    quote: "كم القسط الشهري لسيارة رينزو ٢٠٢٠؟",
    read: "Arabic script, Arabic-Indic digits. Answered from the English bank documents without a translation step, and replied to in both languages.",
    dir: "rtl" as const,
  },
];

export default function WorkflowPage() {
  return (
    <main className="min-h-screen bg-canvas">
      <SiteHeader
        eyebrow="How it works"
        links={[
          { href: "/admin", label: "Operations" },
          { href: "/chat", label: "Open LUMO", cta: true },
        ]}
      />

      {/* ── Hero ─────────────────────────────────────────────────── */}
      <section className="relative overflow-hidden">
        <div
          className="glow-brand pointer-events-none absolute -top-40 right-[-5%] h-[560px] w-[560px]"
          aria-hidden
        />
        <div className="grid-field relative pb-16 pt-16 md:pb-24 md:pt-24">
          <div className="col-span-4 md:col-span-7">
            <Reveal>
              <p className="label mb-5">Technical workflow</p>
            </Reveal>
            <Reveal delay={60}>
              <h1 className="text-display font-semibold text-plum">
                Every inquiry understood, routed and{" "}
                <span className="text-brand">explained.</span>
              </h1>
            </Reveal>
            <Reveal delay={140}>
              <p className="mt-7 max-w-challenge text-lead text-ink-muted">
                Alto Motors receives up to a hundred messages a day across web
                forms and walk-in follow-ups. They mix three requests in one
                sentence, arrive as fragments, and switch between Arabic and
                English mid-thought.
              </p>
              <p className="mt-5 max-w-challenge text-lead text-ink-muted">
                LUMO reads them the way a good coordinator does — and shows its
                reasoning every time.
              </p>
            </Reveal>
          </div>

          <div className="col-span-4 mt-12 flex justify-center md:col-span-4 md:col-start-9 md:mt-0 md:items-center">
            <Reveal delay={120}>
              <Lumo pose="read" size={165} float priority />
            </Reveal>
          </div>

          <div className="col-span-4 mt-14 md:col-span-12 md:mt-20">
            <Reveal delay={200}>
              <dl className="grid grid-cols-2 gap-3 md:grid-cols-4">
                {[
                  ["5 hrs", "Spent routing by hand, daily"],
                  ["11,914", "Vehicles across two brands"],
                  ["6", "Independent confidence signals"],
                  ["0", "Figures written by a model"],
                ].map(([value, caption]) => (
                  <div key={caption} className="card rounded-2xl px-5 py-6">
                    <dt className="tabular text-headline font-semibold text-plum">
                      {value}
                    </dt>
                    <dd className="mt-2 max-w-[22ch] text-caption text-ink-muted">
                      {caption}
                    </dd>
                  </div>
                ))}
              </dl>
            </Reveal>
          </div>
        </div>
      </section>

      {/* ── The problem ──────────────────────────────────────────── */}
      <Section eyebrow="01 — The problem" title="Real messages are not clean.">
        <Reveal delay={120}>
          <div className="mt-12 space-y-4">
            {MESSAGES.map((item) => (
              <div key={item.quote} className="card rounded-3xl p-7 md:p-9">
                <p
                  dir={item.dir}
                  className="text-title font-medium text-plum"
                >
                  “{item.quote}”
                </p>
                <p className="mt-4 max-w-challenge text-small text-ink-muted">
                  {item.read}
                </p>
              </div>
            ))}
          </div>
        </Reveal>
      </Section>

      {/* ── The pipeline ─────────────────────────────────────────── */}
      <Section
        eyebrow="02 — How it thinks"
        title="Four layers, and only one of them is a model."
        lead="The model reports what it heard. The business decides what happens. Keeping those separate is what makes every routing decision reproducible, diffable and explainable."
        wide
      >
        <div className="mt-12 space-y-3">
          {PIPELINE.map((step, index) => (
            <Reveal key={step.n} delay={index * 70}>
              <article className="card card-hover grid grid-cols-4 gap-x-5 gap-y-4 rounded-3xl p-6 md:grid-cols-12 md:p-7">
                <div className="col-span-4 md:col-span-1">
                  <span className="tabular font-mono text-caption text-brand-deep">
                    {step.n}
                  </span>
                </div>

                <div className="col-span-4 md:col-span-3">
                  <h3 className="text-title font-semibold text-plum">
                    {step.layer}
                  </h3>
                  <span
                    className={`chip mt-2 ${
                      step.owner === "Language model"
                        ? "bg-brand-soft text-brand-deep"
                        : "bg-plum-tint text-plum"
                    }`}
                  >
                    {step.owner}
                  </span>
                </div>

                <div className="col-span-4 md:col-span-3">
                  <p className="text-small font-semibold text-ink">{step.q}</p>
                </div>

                <div className="col-span-4 md:col-span-5">
                  <p className="text-small text-ink-muted">{step.detail}</p>
                </div>
              </article>
            </Reveal>
          ))}
        </div>
      </Section>

      {/* ── Confidence ───────────────────────────────────────────── */}
      <Section
        eyebrow="03 — Confidence"
        title="Evidence, not a probability."
        lead="Six signals are measured and shown separately. A system that collapses them into one number cannot answer the only question a reviewer actually asks — what went wrong here?"
      >
        <Reveal delay={120}>
          <ul className="mt-12 grid grid-cols-1 gap-3 sm:grid-cols-2">
            {SIGNALS.map((signal) => (
              <li key={signal.name} className="card rounded-2xl p-5">
                <p className="text-small font-semibold text-plum">
                  {signal.name}
                </p>
                <p className="mt-1.5 text-caption text-ink-muted">
                  {signal.note}
                </p>
              </li>
            ))}
          </ul>
        </Reveal>

        <Reveal delay={180}>
          <div className="card-warm mt-6 rounded-3xl p-7">
            <p className="label mb-5">Where the score lands</p>
            <dl className="space-y-4">
              {[
                ["90 +", "Answered automatically on the fast model", "bg-positive"],
                ["75 – 89", "Escalated to the premium model to reason harder", "bg-brand"],
                ["Below 75", "Drafted and handed to a person", "bg-signal"],
              ].map(([band, meaning, colour]) => (
                <div key={band} className="flex items-baseline gap-4">
                  <span
                    className={`mt-1.5 h-2 w-2 shrink-0 rounded-full ${colour}`}
                    aria-hidden
                  />
                  <dt className="tabular w-24 shrink-0 font-mono text-caption text-plum">
                    {band}
                  </dt>
                  <dd className="text-small text-ink-warm">{meaning}</dd>
                </div>
              ))}
            </dl>
          </div>
        </Reveal>

        <Reveal delay={240}>
          <div className="card mt-6 rounded-3xl p-7">
            <p className="label mb-4">
              Hard overrides — before the score is consulted
            </p>
            <p className="mb-5 max-w-challenge text-small text-ink-muted">
              A weighted average can always be dragged over a threshold by
              strong unrelated signals. These conditions route to a person
              regardless of what the score says.
            </p>
            <ul className="space-y-2.5 rounded-2xl border-l-[3px] border-signal bg-signal/[0.04] py-4 pl-5 pr-4">
              {OVERRIDES.map((line) => (
                <li key={line} className="text-caption text-ink-muted">
                  {line}
                </li>
              ))}
            </ul>
          </div>
        </Reveal>
      </Section>

      {/* ── Storage ──────────────────────────────────────────────── */}
      <Section
        eyebrow="04 — Where facts live"
        title="Two stores, two failure modes, one truthful catalog."
        lead="A vehicle catalog is a table. A policy document is prose. Trying to answer both with the same tool means one of the two is always the wrong tool. So we run both."
      >
        <div className="mt-12 space-y-3">
          {STORES.map((store, index) => (
            <Reveal key={store.name} delay={index * 60}>
              <article className="card card-hover grid grid-cols-4 gap-x-5 gap-y-3 rounded-3xl p-6 md:grid-cols-12">
                <div className="col-span-4 md:col-span-3">
                  <p className="text-small font-semibold text-plum">
                    {store.name}
                  </p>
                  <p className="mt-1 text-caption text-brand-deep">
                    {store.role}
                  </p>
                </div>
                <div className="col-span-4 md:col-span-9">
                  <p className="text-caption text-ink-muted">{store.detail}</p>
                </div>
              </article>
            </Reveal>
          ))}
        </div>
      </Section>

      {/* ── Retrieval funnel ─────────────────────────────────────── */}
      <Section
        eyebrow="05 — Retrieval"
        title="Every score at every stage."
        lead="Retrieval runs dense and keyword search in parallel, fuses the rankings, then reranks. Each stage’s score is kept and shown in the customer UI — so a surprising result can be explained rather than merely accepted."
      >
        <Reveal delay={120}>
          <ol className="mt-12 space-y-3">
            {RETRIEVAL_STAGES.map((stage, index) => (
              <li key={stage.n} className="card flex gap-4 rounded-3xl p-5">
                <span className="tabular flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-brand-soft font-mono text-caption font-bold text-brand-deep">
                  {String(index + 1).padStart(2, "0")}
                </span>
                <div>
                  <p className="text-small font-semibold text-plum">
                    {stage.n}
                  </p>
                  <p className="mt-1 text-caption text-ink-muted">
                    {stage.detail}
                  </p>
                </div>
              </li>
            ))}
          </ol>
        </Reveal>

        <Reveal delay={200}>
          <figure className="card mt-6 overflow-hidden rounded-3xl">
            <figcaption className="flex flex-wrap items-center justify-between gap-2 border-b border-rule bg-offset px-6 py-3.5">
              <span className="label">Retrieved passage</span>
              <span className="font-mono text-caption text-ink-faint">
                cbd-auto-loan-kfs.pdf · p.1
              </span>
            </figcaption>

            <blockquote className="px-6 py-7 text-small text-ink">
              &hellip;interest rate that will remain constant for the approved
              fixed tenure of the loan.{" "}
              <mark className="rounded bg-brand-soft px-1.5 py-0.5 text-brand-deep">
                Following Down Payment 20% of Vehicle value
              </mark>
              &hellip;
            </blockquote>

            <dl className="grid grid-cols-2 gap-3 border-t border-rule bg-offset p-4 sm:grid-cols-4">
              {[
                ["Dense", "0.668"],
                ["BM25", "6.68"],
                ["Fused (RRF)", "0.531"],
                ["Reranked", "0.66"],
              ].map(([stage, score]) => (
                <div key={stage} className="rounded-xl bg-paper px-4 py-3">
                  <dt className="label-muted">{stage}</dt>
                  <dd className="tabular mt-1.5 font-mono text-small text-plum">
                    {score}
                  </dd>
                </div>
              ))}
            </dl>
          </figure>

          <p className="mt-4 text-caption text-ink-faint">
            Live figures from the indexed corpus — six UAE auto-finance
            documents, ten Alto Motors policy documents, and the vehicle
            catalog. Around forty thousand words of grounded evidence.
          </p>
        </Reveal>
      </Section>

      {/* ── The two brands ───────────────────────────────────────── */}
      <Section
        eyebrow="06 — The ecosystem"
        title="Two brands, one catalogue."
        wide
      >
        <div className="mt-12 grid grid-cols-1 gap-6 md:grid-cols-2">
          {[
            {
              brand: "Karva",
              count: "9,015",
              line: "Affordable sedans and SUVs",
              body: "The volume of the showroom floor. Most financing questions, most trade-ins, most Saturday test drives.",
              bar: "bg-brand",
              tint: "bg-brand-soft",
              edge: "border-brand-edge",
            },
            {
              brand: "Renzo",
              count: "2,899",
              line: "Premium and performance",
              body: "Higher value, stricter eligibility, and a longer conversation. Performance models carry their own test-drive rules.",
              bar: "bg-plum-soft",
              tint: "bg-plum-tint",
              edge: "border-plum/15",
            },
          ].map((brand) => (
            <Reveal key={brand.brand}>
              <article
                className={`card-hover h-full rounded-panel border ${brand.edge} ${brand.tint} p-9 md:p-11`}
              >
                <div
                  className={`h-1.5 w-14 rounded-full ${brand.bar}`}
                  aria-hidden
                />
                <h3 className="mt-7 text-headline font-semibold text-plum">
                  {brand.brand}
                </h3>
                <p className="mt-3 text-small text-ink-muted">{brand.line}</p>

                <p className="tabular mt-8 inline-flex items-baseline gap-2 rounded-xl bg-paper px-4 py-2 text-title font-semibold text-plum shadow-soft">
                  {brand.count}
                  <span className="text-caption font-normal text-ink-muted">
                    vehicles
                  </span>
                </p>

                <p className="mt-7 max-w-challenge text-small text-ink-muted">
                  {brand.body}
                </p>
              </article>
            </Reveal>
          ))}
        </div>
      </Section>

      {/* ── What it refuses to do ────────────────────────────────── */}
      <section className="grid-field pb-section">
        <div className="col-span-4 md:col-span-12">
          <Reveal>
            <div className="relative overflow-hidden rounded-panel bg-plum px-7 py-14 md:px-14 md:py-20">
              <div
                className="glow-plum pointer-events-none absolute inset-x-0 -top-40 h-[560px]"
                aria-hidden
              />
              <div className="relative grid grid-cols-4 gap-x-5 md:grid-cols-12">
                <div className="col-span-4 md:col-span-4">
                  <p className="label-muted !text-brand">07 — Restraint</p>
                  <h2 className="mt-4 text-headline font-semibold text-white">
                    What it refuses to do.
                  </h2>
                  <p className="mt-5 text-lead text-white/60">
                    Trust in a system like this is built from the things it
                    declines to guess.
                  </p>
                  <div className="mt-10 hidden justify-start md:flex">
                    <Lumo pose="cape" size={140} />
                  </div>
                </div>

                <div className="col-span-4 mt-10 md:col-span-7 md:col-start-6 md:mt-0">
                  <div className="space-y-px">
                    {REFUSALS.map((item, index) => (
                      <Reveal key={item.title} delay={index * 60}>
                        <div className="border-t border-white/10 py-7">
                          <h3 className="text-title font-medium text-white">
                            {item.title}
                          </h3>
                          <p className="mt-3 max-w-challenge text-small text-white/60">
                            {item.body}
                          </p>
                        </div>
                      </Reveal>
                    ))}
                  </div>
                </div>
              </div>
            </div>
          </Reveal>
        </div>
      </section>

      {/* ── Handoff ──────────────────────────────────────────────── */}
      <Section
        eyebrow="08 — Handoff, not handover"
        title="A person can take the same conversation."
        lead="When a message escalates, a member of the team sees the full transcript in the operations view — not just the last drafted line. They can send the draft as-is, edit it, or write their own reply. From that point on LUMO steps aside and the operator continues the thread live."
      >
        <Reveal delay={120}>
          <p className="mt-8 max-w-challenge text-small text-ink-muted">
            The customer never notices the change, except that the answers get
            better.
          </p>
        </Reveal>
      </Section>

      {/* ── Call to action ───────────────────────────────────────── */}
      <section className="grid-field pb-section">
        <div className="col-span-4 md:col-span-12">
          <Reveal>
            <div className="card-warm rounded-panel px-8 py-14 md:px-16">
              <div className="flex flex-col items-center gap-10 md:flex-row md:justify-between">
                <div className="max-w-xl text-center md:text-left">
                  <h2 className="text-headline font-semibold text-plum">
                    See it reason.
                  </h2>
                  <p className="mt-4 text-lead text-ink-warm">
                    Send it something difficult. Three requests at once, a
                    fragment with no context, or a question in Arabic. Then
                    open the operations view and watch the decision being made.
                  </p>
                  <div className="mt-8 flex flex-wrap justify-center gap-3 md:justify-start">
                    <Link href="/chat" className="btn-primary btn-lg">
                      Open LUMO
                    </Link>
                    <Link href="/admin" className="btn-ghost btn-lg">
                      Operations view
                    </Link>
                  </div>
                </div>
                <Lumo pose="heart" size={140} className="shrink-0" />
              </div>
            </div>
          </Reveal>
        </div>
      </section>

      <SiteFooter note="The financing corpus consists of real UAE regulatory and banking documents, retained verbatim and labelled as such. Quotes are indicative and are not finance offers." />
    </main>
  );
}

/**
 * Section scaffold.
 *
 * Eight sections previously repeated the same three-column heading block by
 * hand, which is how they drifted apart. `wide` widens the body to the full
 * field for sections whose content is a grid rather than prose.
 */
function Section({
  eyebrow,
  title,
  lead,
  wide = false,
  children,
}: {
  eyebrow: string;
  title: string;
  lead?: string;
  wide?: boolean;
  children: React.ReactNode;
}) {
  return (
    <section className="grid-field pb-section">
      <div className="col-span-4 md:col-span-3">
        <Reveal>
          <p className="label md:sticky md:top-28">{eyebrow}</p>
        </Reveal>
      </div>

      {/* A `wide` body cannot share the row with the eyebrow, so it wraps
          beneath it and has to restore the gap the side-by-side layout gets
          for free. */}
      <div
        className={`col-span-4 mt-5 ${
          wide ? "md:col-span-12 md:mt-6" : "md:col-span-8 md:col-start-5 md:mt-0"
        }`}
      >
        <Reveal delay={60}>
          <h2 className="text-headline font-semibold text-plum">{title}</h2>
          {lead && (
            <p className="mt-6 max-w-challenge text-lead text-ink-muted">
              {lead}
            </p>
          )}
        </Reveal>
        {children}
      </div>
    </section>
  );
}
