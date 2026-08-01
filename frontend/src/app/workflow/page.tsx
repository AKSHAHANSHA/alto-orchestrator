import Link from "next/link";
import { Reveal } from "@/components/Reveal";

/**
 * Technical workflow page.
 *
 * The place the previous landing page lived, plus more architectural depth
 * that didn't fit a general-audience front door: the four cognitive layers,
 * the six confidence signals, the retrieval funnel, the graph shape, and the
 * three things the platform will refuse to guess. Meant to be read by
 * engineers, technical leads, and anyone deciding whether to trust an AI
 * system with real customer conversations.
 *
 * Kept as one scrolling narrative on the same Swiss grid, so a reader who
 * arrives here from the customer landing lands in a consistent visual world.
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
  { n: "Prefetch × 2", detail: "Dense multilingual embedding and sparse BM25 with the IDF modifier, each returning the top 100 candidates. They run in parallel." },
  { n: "Server-side RRF", detail: "Qdrant fuses the two rankings with Reciprocal Rank Fusion. No score-scale blending — RRF discards magnitudes and combines ranks, which is the only mathematically sound way to fuse two retrievers that don't share a scale." },
  { n: "Cross-encoder rerank", detail: "The top 20 fused candidates are rescored by a local cross-encoder. English-only, so Arabic queries skip this stage and keep the fusion ranking — silently degrading beats scrambling a good order." },
  { n: "Top-K", detail: "Five chunks reach the generator. Every score at every stage is stored on the chunk and shown in the customer UI." },
];

const OVERRIDES = [
  "Any complaint keyword — routes to a person, always",
  "Negative sentiment combined with high urgency — routes to a person",
  "An answer citing a number the evidence doesn't support — routes to a person",
  "A financial claim without a supporting document — routes to a person",
  "A conversation any human has already touched — stays with the human",
];

export default function WorkflowPage() {
  return (
    <main className="min-h-screen bg-paper">
      {/* ── Masthead ─────────────────────────────────────────────── */}
      <header className="sticky top-0 z-50 border-b border-rule bg-paper/90 backdrop-blur-sm">
        <div className="grid-field h-16 items-center">
          <Link
            href="/"
            className="col-span-2 flex items-center gap-3 md:col-span-4"
          >
            <span className="block h-3 w-3 bg-ink" aria-hidden />
            <span className="text-caption font-medium tracking-tight">
              Alto Motors
            </span>
          </Link>
          <nav className="col-span-2 flex items-center justify-end gap-8 md:col-span-8">
            <Link
              href="/"
              className="hidden text-caption text-ink-muted transition-colors hover:text-ink sm:block"
            >
              Home
            </Link>
            <Link
              href="/admin"
              className="hidden text-caption text-ink-muted transition-colors hover:text-ink sm:block"
            >
              Operations
            </Link>
            <Link
              href="/chat"
              className="bg-ink px-4 py-2 text-caption text-paper transition-opacity hover:opacity-85"
            >
              Open the assistant
            </Link>
          </nav>
        </div>
      </header>

      {/* ── Hero ─────────────────────────────────────────────────── */}
      <section className="grid-field pb-section pt-24 md:pt-40">
        <div className="col-span-4 md:col-span-12">
          <Reveal>
            <p className="label mb-10">Technical workflow</p>
          </Reveal>
        </div>

        <div className="col-span-4 md:col-span-9">
          <Reveal delay={60}>
            <h1 className="text-display font-semibold">
              Every inquiry
              <br />
              understood,
              <br />
              routed and
              <br />
              <span className="text-ink-faint">explained.</span>
            </h1>
          </Reveal>
        </div>

        <div className="col-span-4 mt-14 md:col-span-5 md:col-start-8 md:mt-24">
          <Reveal delay={140}>
            <p className="text-lead text-ink-muted">
              Alto Motors receives up to a hundred messages a day across web
              forms and walk-in follow-ups. They mix three requests in one
              sentence, arrive as fragments, and switch between Arabic and
              English mid-thought.
            </p>
            <p className="mt-6 text-lead text-ink-muted">
              This platform reads them the way a good coordinator does — and
              shows its reasoning every time.
            </p>
          </Reveal>
        </div>

        <div className="col-span-4 mt-20 md:col-span-12 md:mt-32">
          <Reveal delay={200}>
            <dl className="grid grid-cols-2 gap-y-10 border-t border-ink pt-8 md:grid-cols-4">
              {[
                ["5 hrs", "Spent routing by hand, daily"],
                ["11,914", "Vehicles across two brands"],
                ["6", "Independent confidence signals"],
                ["0", "Figures written by a model"],
              ].map(([value, caption]) => (
                <div key={caption}>
                  <dt className="tabular text-headline font-semibold">
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
      </section>

      {/* ── The problem ──────────────────────────────────────────── */}
      <section className="border-t border-rule bg-offset py-section">
        <div className="grid-field">
          <div className="col-span-4 md:col-span-3">
            <Reveal>
              <p className="label">01 — The problem</p>
            </Reveal>
          </div>

          <div className="col-span-4 md:col-span-8 md:col-start-5">
            <Reveal delay={60}>
              <h2 className="text-headline font-semibold">
                Real messages are not clean.
              </h2>
            </Reveal>

            <Reveal delay={120}>
              <div className="mt-14 space-y-px bg-rule">
                {[
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
                ].map((item) => (
                  <div key={item.quote} className="bg-paper p-8 md:p-10">
                    <p
                      dir={item.dir}
                      className="text-title font-medium text-ink"
                    >
                      “{item.quote}”
                    </p>
                    <p className="mt-5 max-w-challenge text-body text-ink-muted">
                      {item.read}
                    </p>
                  </div>
                ))}
              </div>
            </Reveal>
          </div>
        </div>
      </section>

      {/* ── The pipeline ─────────────────────────────────────────── */}
      <section className="py-section">
        <div className="grid-field">
          <div className="col-span-4 md:col-span-3">
            <Reveal>
              <p className="label">02 — How it thinks</p>
            </Reveal>
          </div>

          <div className="col-span-4 md:col-span-8 md:col-start-5">
            <Reveal delay={60}>
              <h2 className="text-headline font-semibold">
                Four layers, and only one of them is a model.
              </h2>
              <p className="mt-8 max-w-challenge text-lead text-ink-muted">
                The model reports what it heard. The business decides what
                happens. Keeping those separate is what makes every routing
                decision reproducible, diffable and explainable.
              </p>
            </Reveal>
          </div>

          <div className="col-span-4 mt-20 md:col-span-12">
            <div className="border-t border-ink">
              {PIPELINE.map((step, index) => (
                <Reveal key={step.n} delay={index * 70}>
                  <article className="grid grid-cols-4 gap-x-5 border-b border-rule py-10 md:grid-cols-12">
                    <div className="col-span-4 md:col-span-1">
                      <span className="tabular font-mono text-caption text-ink-faint">
                        {step.n}
                      </span>
                    </div>

                    <div className="col-span-4 mt-3 md:col-span-3 md:mt-0">
                      <h3 className="text-title font-semibold">{step.layer}</h3>
                      <span
                        className={`mt-3 inline-block px-2 py-1 text-label uppercase ${
                          step.owner === "Language model"
                            ? "bg-karva-soft text-karva"
                            : "bg-renzo-soft text-renzo"
                        }`}
                      >
                        {step.owner}
                      </span>
                    </div>

                    <div className="col-span-4 mt-4 md:col-span-3 md:mt-0">
                      <p className="text-body font-medium">{step.q}</p>
                    </div>

                    <div className="col-span-4 mt-3 md:col-span-5 md:mt-0">
                      <p className="text-body text-ink-muted">{step.detail}</p>
                    </div>
                  </article>
                </Reveal>
              ))}
            </div>
          </div>
        </div>
      </section>

      {/* ── Confidence ───────────────────────────────────────────── */}
      <section className="border-t border-rule bg-offset py-section">
        <div className="grid-field">
          <div className="col-span-4 md:col-span-3">
            <Reveal>
              <p className="label">03 — Confidence</p>
            </Reveal>
          </div>

          <div className="col-span-4 md:col-span-8 md:col-start-5">
            <Reveal delay={60}>
              <h2 className="text-headline font-semibold">
                Evidence, not a probability.
              </h2>
              <p className="mt-8 max-w-challenge text-lead text-ink-muted">
                Six signals are measured and shown separately. A system that
                collapses them into one number cannot answer the only question
                a reviewer actually asks — what went wrong here?
              </p>
            </Reveal>

            <Reveal delay={120}>
              <ul className="mt-14 grid grid-cols-1 gap-px bg-rule sm:grid-cols-2">
                {SIGNALS.map((signal) => (
                  <li key={signal.name} className="bg-offset p-6">
                    <p className="text-body font-medium">{signal.name}</p>
                    <p className="mt-1.5 text-caption text-ink-muted">
                      {signal.note}
                    </p>
                  </li>
                ))}
              </ul>
            </Reveal>

            <Reveal delay={180}>
              <div className="mt-14 border-t border-ink pt-8">
                <p className="label mb-6">Where the score lands</p>
                <dl className="space-y-5">
                  {[
                    ["90 +", "Answered automatically on the fast model", "bg-positive"],
                    ["75 – 89", "Escalated to the premium model to reason harder", "bg-renzo"],
                    ["Below 75", "Drafted and handed to a person", "bg-signal"],
                  ].map(([band, meaning, colour]) => (
                    <div key={band} className="flex items-baseline gap-5">
                      <span
                        className={`mt-1.5 h-2 w-2 shrink-0 ${colour}`}
                        aria-hidden
                      />
                      <dt className="tabular w-24 shrink-0 font-mono text-caption">
                        {band}
                      </dt>
                      <dd className="text-body text-ink-muted">{meaning}</dd>
                    </div>
                  ))}
                </dl>
              </div>
            </Reveal>

            <Reveal delay={240}>
              <div className="mt-14 border-t border-ink pt-8">
                <p className="label mb-6">Hard overrides — before the score is consulted</p>
                <p className="mb-6 max-w-challenge text-body text-ink-muted">
                  A weighted average can always be dragged over a threshold by
                  strong unrelated signals. These conditions route to a person
                  regardless of what the score says.
                </p>
                <ul className="space-y-3 border-l-2 border-signal pl-5">
                  {OVERRIDES.map((line) => (
                    <li key={line} className="text-caption text-ink-muted">
                      {line}
                    </li>
                  ))}
                </ul>
              </div>
            </Reveal>
          </div>
        </div>
      </section>

      {/* ── Storage ──────────────────────────────────────────────── */}
      <section className="py-section">
        <div className="grid-field">
          <div className="col-span-4 md:col-span-3">
            <Reveal>
              <p className="label">04 — Where facts live</p>
            </Reveal>
          </div>

          <div className="col-span-4 md:col-span-8 md:col-start-5">
            <Reveal delay={60}>
              <h2 className="text-headline font-semibold">
                Two stores, two failure modes, one truthful catalog.
              </h2>
              <p className="mt-8 max-w-challenge text-lead text-ink-muted">
                A vehicle catalog is a table. A policy document is prose.
                Trying to answer both with the same tool means one of the two
                is always the wrong tool. So we run both.
              </p>
            </Reveal>

            <div className="mt-14 space-y-px bg-rule">
              {STORES.map((store, index) => (
                <Reveal key={store.name} delay={index * 60}>
                  <article className="grid grid-cols-4 gap-x-5 bg-paper p-6 md:grid-cols-12">
                    <div className="col-span-4 md:col-span-3">
                      <p className="text-body font-medium">{store.name}</p>
                      <p className="mt-1 text-caption text-ink-faint">
                        {store.role}
                      </p>
                    </div>
                    <div className="col-span-4 mt-3 md:col-span-9 md:mt-0">
                      <p className="text-caption text-ink-muted">
                        {store.detail}
                      </p>
                    </div>
                  </article>
                </Reveal>
              ))}
            </div>
          </div>
        </div>
      </section>

      {/* ── Retrieval funnel ─────────────────────────────────────── */}
      <section className="border-t border-rule bg-offset py-section">
        <div className="grid-field">
          <div className="col-span-4 md:col-span-3">
            <Reveal>
              <p className="label">05 — Retrieval</p>
            </Reveal>
          </div>

          <div className="col-span-4 md:col-span-8 md:col-start-5">
            <Reveal delay={60}>
              <h2 className="text-headline font-semibold">
                Every score at every stage.
              </h2>
              <p className="mt-8 max-w-challenge text-lead text-ink-muted">
                Retrieval runs dense and keyword search in parallel, fuses the
                rankings, then reranks. Each stage&rsquo;s score is kept and
                shown in the customer UI — so a surprising result can be
                explained rather than merely accepted.
              </p>
            </Reveal>

            <Reveal delay={120}>
              <ol className="mt-14 space-y-4">
                {RETRIEVAL_STAGES.map((stage, index) => (
                  <li
                    key={stage.n}
                    className="flex gap-5 border-l-2 border-ink bg-paper p-5"
                  >
                    <span className="tabular w-6 shrink-0 font-mono text-caption text-ink-faint">
                      {String(index + 1).padStart(2, "0")}
                    </span>
                    <div>
                      <p className="text-body font-medium">{stage.n}</p>
                      <p className="mt-1 text-caption text-ink-muted">
                        {stage.detail}
                      </p>
                    </div>
                  </li>
                ))}
              </ol>
            </Reveal>

            <Reveal delay={200}>
              <figure className="mt-14 border border-rule">
                <figcaption className="flex items-center justify-between border-b border-rule px-6 py-3">
                  <span className="label">Retrieved passage</span>
                  <span className="font-mono text-caption text-ink-faint">
                    cbd-auto-loan-kfs.pdf · p.1
                  </span>
                </figcaption>

                <blockquote className="px-6 py-7 text-body">
                  &hellip;interest rate that will remain constant for the
                  approved fixed tenure of the loan.{" "}
                  <mark className="bg-karva-soft px-1">
                    Following Down Payment 20% of Vehicle value
                  </mark>
                  &hellip;
                </blockquote>

                <dl className="grid grid-cols-2 gap-px border-t border-rule bg-rule sm:grid-cols-4">
                  {[
                    ["Dense", "0.668"],
                    ["BM25", "6.68"],
                    ["Fused (RRF)", "0.531"],
                    ["Reranked", "0.66"],
                  ].map(([stage, score]) => (
                    <div key={stage} className="bg-paper px-5 py-4">
                      <dt className="label">{stage}</dt>
                      <dd className="tabular mt-1.5 font-mono text-body">
                        {score}
                      </dd>
                    </div>
                  ))}
                </dl>
              </figure>

              <p className="mt-5 text-caption text-ink-faint">
                Live figures from the indexed corpus — six UAE auto-finance
                documents, ten Alto Motors policy documents, and the vehicle
                catalog. Around forty thousand words of grounded evidence.
              </p>
            </Reveal>
          </div>
        </div>
      </section>

      {/* ── The two brands ───────────────────────────────────────── */}
      <section className="py-section">
        <div className="grid-field">
          <div className="col-span-4 md:col-span-3">
            <Reveal>
              <p className="label">06 — The ecosystem</p>
            </Reveal>
          </div>

          <div className="col-span-4 md:col-span-8 md:col-start-5">
            <Reveal delay={60}>
              <h2 className="text-headline font-semibold">Two brands, one catalogue.</h2>
            </Reveal>
          </div>

          <div className="col-span-4 mt-16 md:col-span-12">
            <div className="grid grid-cols-1 gap-px bg-rule md:grid-cols-2">
              {[
                {
                  brand: "Karva",
                  count: "9,015",
                  line: "Affordable sedans and SUVs",
                  body: "The volume of the showroom floor. Most financing questions, most trade-ins, most Saturday test drives.",
                  bar: "bg-karva",
                  tint: "bg-karva-soft",
                },
                {
                  brand: "Renzo",
                  count: "2,899",
                  line: "Premium and performance",
                  body: "Higher value, stricter eligibility, and a longer conversation. Performance models carry their own test-drive rules.",
                  bar: "bg-renzo",
                  tint: "bg-renzo-soft",
                },
              ].map((brand) => (
                <Reveal key={brand.brand}>
                  <article className="h-full bg-paper p-10 md:p-14">
                    <div className={`h-1 w-16 ${brand.bar}`} aria-hidden />
                    <h3 className="mt-8 text-headline font-semibold">
                      {brand.brand}
                    </h3>
                    <p className="mt-3 text-body text-ink-muted">{brand.line}</p>

                    <p
                      className={`tabular mt-10 inline-block px-3 py-1.5 text-title font-semibold ${brand.tint}`}
                    >
                      {brand.count}
                      <span className="ml-2 text-caption font-normal text-ink-muted">
                        vehicles
                      </span>
                    </p>

                    <p className="mt-8 max-w-challenge text-body text-ink-muted">
                      {brand.body}
                    </p>
                  </article>
                </Reveal>
              ))}
            </div>
          </div>
        </div>
      </section>

      {/* ── What it refuses to do ────────────────────────────────── */}
      <section className="border-t border-rule bg-ink py-section text-paper">
        <div className="grid-field">
          <div className="col-span-4 md:col-span-3">
            <Reveal>
              <p className="label !text-paper/50">07 — Restraint</p>
            </Reveal>
          </div>

          <div className="col-span-4 md:col-span-8 md:col-start-5">
            <Reveal delay={60}>
              <h2 className="text-headline font-semibold">
                What it refuses to do.
              </h2>
              <p className="mt-8 max-w-challenge text-lead text-paper/60">
                Trust in a system like this is built from the things it declines
                to guess.
              </p>
            </Reveal>

            <div className="mt-16 space-y-px">
              {REFUSALS.map((item, index) => (
                <Reveal key={item.title} delay={index * 70}>
                  <div className="border-t border-paper/15 py-8">
                    <h3 className="text-title font-medium">{item.title}</h3>
                    <p className="mt-4 max-w-challenge text-body text-paper/60">
                      {item.body}
                    </p>
                  </div>
                </Reveal>
              ))}
            </div>
          </div>
        </div>
      </section>

      {/* ── Handoff ──────────────────────────────────────────────── */}
      <section className="py-section">
        <div className="grid-field">
          <div className="col-span-4 md:col-span-3">
            <Reveal>
              <p className="label">08 — Handoff, not handover</p>
            </Reveal>
          </div>

          <div className="col-span-4 md:col-span-8 md:col-start-5">
            <Reveal delay={60}>
              <h2 className="text-headline font-semibold">
                A person can take the same conversation.
              </h2>
              <p className="mt-8 max-w-challenge text-lead text-ink-muted">
                When a message escalates, a member of the team sees the full
                transcript in the operations view — not just the last drafted
                line. They can send the draft as-is, edit it, or write their
                own reply. From that point on the assistant steps aside and
                the operator continues the thread live.
              </p>
              <p className="mt-6 max-w-challenge text-body text-ink-muted">
                The customer never notices the change, except that the answers
                get better.
              </p>
            </Reveal>
          </div>
        </div>
      </section>

      {/* ── Call to action ───────────────────────────────────────── */}
      <section className="border-t border-ink py-section">
        <div className="grid-field">
          <div className="col-span-4 md:col-span-9">
            <Reveal>
              <h2 className="text-display font-semibold">
                See it reason.
              </h2>
            </Reveal>
          </div>

          <div className="col-span-4 mt-12 md:col-span-6 md:mt-16">
            <Reveal delay={80}>
              <p className="text-lead text-ink-muted">
                Send it something difficult. Three requests at once, a fragment
                with no context, or a question in Arabic. Then open the
                operations view and watch the decision being made.
              </p>

              <div className="mt-12 flex flex-wrap gap-4">
                <Link
                  href="/chat"
                  className="bg-ink px-8 py-4 text-body text-paper transition-opacity hover:opacity-85"
                >
                  Open the assistant
                </Link>
                <Link
                  href="/admin"
                  className="border border-ink px-8 py-4 text-body transition-colors hover:bg-ink hover:text-paper"
                >
                  Operations view
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
              The financing corpus consists of real UAE regulatory and banking
              documents, retained verbatim and labelled as such. Quotes are
              indicative and are not finance offers.
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
