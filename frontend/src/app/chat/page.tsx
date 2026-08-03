"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  api,
  fmt,
  type Chunk,
  type InquiryResponse,
  type Span,
  type TranscriptTurn,
} from "@/lib/api";
import { CalendarPicker } from "@/components/CalendarPicker";

/**
 * Customer view.
 *
 * Two things distinguish it from an ordinary chat window: the reply carries
 * its provenance, and it carries its uncertainty. Every retrieved passage is
 * expandable and shows all four ranking scores; every answer states which
 * model produced it, how confident the system was, and whether a person still
 * needs to see it.
 *
 * Conversation identity survives page reloads and cross-view navigation by
 * living in localStorage — leaving `/chat` for `/admin` used to abandon the
 * session, so a customer coming back saw an empty page. After the reload the
 * transcript is fetched from the server, which is also what lets an operator
 * reply (composed in the operations view) appear in the customer's window.
 */

const EXAMPLES = [
  "I want to trade in my old Karva SUV and also check financing for a new Renzo S5 — and can I test drive it Saturday?",
  "is this still available?",
  "كم القسط الشهري لسيارة رينزو 2020؟",
  "This is unacceptable, I have been waiting for weeks.",
];

const CONVERSATION_KEY = "alto:conversation_id";

interface Turn {
  role: "customer" | "assistant" | "system";
  text: string;
  arabic?: string | null;
  response?: InquiryResponse;
}

function isArabic(text: string): boolean {
  return /[؀-ۿ]/.test(text);
}

interface CalendarPrompt {
  vehicleLabel: string;
}

export default function ChatPage() {
  const [turns, setTurns] = useState<Turn[]>([]);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [awaitingHuman, setAwaitingHuman] = useState(false);
  const [calendarPrompt, setCalendarPrompt] = useState<CalendarPrompt | null>(null);
  const conversationId = useRef<string | undefined>(undefined);

  // Restore the session on mount. If the browser has a conversation id, ask
  // the server for its transcript — that survives page reloads, navigating
  // to the operations view and back, and any assistant replies an operator
  // composed after a handoff.
  const restore = useCallback(async () => {
    if (typeof window === "undefined") return;
    const stored = window.localStorage.getItem(CONVERSATION_KEY);
    if (!stored) return;
    conversationId.current = stored;

    try {
      const state = await api.getConversation(stored);
      setTurns(
        state.transcript.map(
          (turn: TranscriptTurn): Turn => ({
            role: (turn.role as Turn["role"]) ?? "assistant",
            text: turn.text,
          }),
        ),
      );
      setAwaitingHuman(state.human_handled);
    } catch {
      // Server has forgotten this conversation (restart, memory eviction).
      // Clear the stale id so the next message starts a fresh one, without
      // the user having to know they need to.
      window.localStorage.removeItem(CONVERSATION_KEY);
      conversationId.current = undefined;
    }
  }, []);

  useEffect(() => {
    void restore();
  }, [restore]);

  // Once the conversation is with a human, poll for their reply. The graph
  // is skipped for these turns, so ``submitInquiry`` no longer produces
  // assistant text — the transcript is the only place their message lives.
  useEffect(() => {
    if (!awaitingHuman || !conversationId.current) return;

    const timer = setInterval(async () => {
      const id = conversationId.current;
      if (!id) return;
      try {
        const state = await api.getConversation(id);
        setTurns((prev) => {
          if (state.transcript.length <= prev.length) return prev;
          return state.transcript.map((turn) => ({
            role: (turn.role as Turn["role"]) ?? "assistant",
            text: turn.text,
          }));
        });
      } catch {
        /* transient; try again on the next tick */
      }
    }, 4000);

    return () => clearInterval(timer);
  }, [awaitingHuman]);

  async function send(message: string) {
    if (!message.trim() || busy) return;

    setBusy(true);
    setError(null);
    setDraft("");
    setTurns((prev) => [...prev, { role: "customer", text: message }]);

    try {
      const response = await api.submitInquiry(message, conversationId.current);
      conversationId.current = response.conversation_id;
      if (typeof window !== "undefined") {
        window.localStorage.setItem(CONVERSATION_KEY, response.conversation_id);
      }
      if (response.escalated || response.awaiting === "human_response") {
        setAwaitingHuman(true);
      }

      setTurns((prev) => [
        ...prev,
        {
          role: "assistant",
          text: response.reply?.en ?? "This has been passed to a colleague.",
          arabic: response.reply?.ar,
          response,
        },
      ]);

      // If the backend detected a booking-ready state, show the calendar.
      // Deriving the vehicle label from the intent entities keeps the
      // confirmation message specific and grounded.
      if (response.awaiting === "test_drive_slot") {
        setCalendarPrompt({ vehicleLabel: vehicleLabelFrom(response) });
      } else {
        setCalendarPrompt(null);
      }
    } catch (exception) {
      setError(
        exception instanceof Error
          ? exception.message
          : "Could not reach the orchestrator.",
      );
    } finally {
      setBusy(false);
    }
  }

  function newConversation() {
    if (typeof window !== "undefined") {
      window.localStorage.removeItem(CONVERSATION_KEY);
    }
    conversationId.current = undefined;
    setTurns([]);
    setAwaitingHuman(false);
    setError(null);
    setCalendarPrompt(null);
  }

  function handleBooked(confirmation: string) {
    setCalendarPrompt(null);
    setTurns((prev) => [...prev, { role: "assistant", text: confirmation }]);
  }

  return (
    <div className="min-h-screen bg-paper">
      <header className="sticky top-0 z-40 border-b border-rule bg-paper/95 backdrop-blur-sm">
        <div className="grid-field h-16 items-center">
          <Link
            href="/"
            className="col-span-2 flex items-center gap-3 md:col-span-4"
          >
            <span className="block h-3 w-3 bg-ink" aria-hidden />
            <span className="text-caption font-medium">Alto Motors</span>
          </Link>
          <div className="col-span-2 flex items-center justify-end gap-5 md:col-span-8">
            {turns.length > 0 && (
              <button
                type="button"
                onClick={newConversation}
                className="text-caption text-ink-muted hover:text-ink"
              >
                Start over
              </button>
            )}
            <Link
              href="/admin"
              className="text-caption text-ink-muted hover:text-ink"
            >
              Operations view
            </Link>
          </div>
        </div>
      </header>

      <main className="grid-field py-12">
        <div className="col-span-4 md:col-span-8 md:col-start-3">
          {turns.length === 0 && (
            <section className="mb-12">
              <h1 className="text-headline font-semibold">
                How can we help?
              </h1>
              <p className="mt-5 max-w-challenge text-lead text-ink-muted">
                Ask about a vehicle, financing, a trade-in or a test drive — in
                English or Arabic. Mixing several questions in one message is
                fine; that is what this is built for.
              </p>

              <p className="label mt-12 mb-4">Try one of these</p>
              <div className="space-y-px bg-rule">
                {EXAMPLES.map((example) => (
                  <button
                    key={example}
                    type="button"
                    onClick={() => send(example)}
                    dir={isArabic(example) ? "rtl" : "ltr"}
                    className="block w-full bg-paper p-5 text-left text-body transition-colors hover:bg-offset"
                  >
                    {example}
                  </button>
                ))}
              </div>
            </section>
          )}

          {awaitingHuman && turns.length > 0 && (
            <div className="mb-8 border-l-2 border-renzo bg-renzo-soft px-5 py-3 text-caption text-ink">
              A member of our team is handling this conversation. Their reply
              will appear here shortly.
            </div>
          )}

          <div className="space-y-10">
            {turns.map((turn, index) =>
              turn.role === "customer" ? (
                <CustomerTurn key={index} text={turn.text} />
              ) : turn.role === "system" ? (
                <SystemTurn key={index} text={turn.text} />
              ) : (
                <AssistantTurn key={index} turn={turn} />
              ),
            )}

            {calendarPrompt && conversationId.current && (
              <CalendarPicker
                conversationId={conversationId.current}
                vehicleLabel={calendarPrompt.vehicleLabel}
                onBooked={handleBooked}
                onCancel={() => setCalendarPrompt(null)}
              />
            )}

            {busy && (
              <p className="label animate-pulse">Thinking…</p>
            )}

            {error && (
              <p className="border-l-2 border-signal bg-offset px-5 py-4 text-body text-signal">
                {error}
              </p>
            )}
          </div>

          <form
            onSubmit={(event) => {
              event.preventDefault();
              void send(draft);
            }}
            className="sticky bottom-0 mt-14 border-t border-ink bg-paper pt-5 pb-8"
          >
            <div className="flex gap-3">
              <input
                value={draft}
                onChange={(event) => setDraft(event.target.value)}
                placeholder="Write your message…"
                disabled={busy}
                dir={isArabic(draft) ? "rtl" : "ltr"}
                className="flex-1 border border-rule px-5 py-4 text-body outline-none transition-colors focus:border-ink disabled:opacity-50"
              />
              <button
                type="submit"
                disabled={busy || !draft.trim()}
                className="bg-ink px-8 text-caption text-paper transition-opacity hover:opacity-85 disabled:opacity-30"
              >
                Send
              </button>
            </div>
          </form>
        </div>
      </main>
    </div>
  );
}

function vehicleLabelFrom(response: InquiryResponse): string {
  // Assistants and reviewers both benefit from a specific label ("2020
  // Karva Acadia") over a generic "test drive". Derive it from the
  // extracted entities when we can; fall back gracefully.
  const entities = response.entities as Array<{ type?: string; value?: string }>;
  const byType = new Map<string, string>();
  for (const entity of entities) {
    if (typeof entity.type === "string" && typeof entity.value === "string") {
      byType.set(entity.type, entity.value);
    }
  }
  const parts = [
    byType.get("new_vehicle_year"),
    byType.get("new_vehicle_brand"),
    byType.get("new_vehicle_model"),
  ].filter(Boolean);
  return parts.length > 0 ? parts.join(" ") : "test drive";
}

function CustomerTurn({ text }: { text: string }) {
  const rtl = isArabic(text);
  return (
    <div className="flex justify-end">
      <p
        dir={rtl ? "rtl" : "ltr"}
        className="max-w-[85%] bg-ink px-6 py-4 text-body text-paper"
      >
        {text}
      </p>
    </div>
  );
}

function SystemTurn({ text }: { text: string }) {
  return (
    <p className="text-center text-caption text-ink-faint italic">{text}</p>
  );
}

function AssistantTurn({ turn }: { turn: Turn }) {
  const response = turn.response;
  const routing = response?.routing;
  const rtl = isArabic(turn.text);

  return (
    <article className="border-l-2 border-ink pl-6">
      <p dir={rtl ? "rtl" : "ltr"} className="text-body">
        {turn.text}
      </p>

      {turn.arabic && (
        <p dir="rtl" className="mt-5 border-t border-rule pt-5 text-body">
          {turn.arabic}
        </p>
      )}

      {response && (
        <>
          <ul className="mt-6 flex flex-wrap items-center gap-x-5 gap-y-2 text-caption text-ink-faint">
            {response.confidence && (
              <li className="tabular">
                Confidence{" "}
                <strong className="font-medium text-ink">
                  {response.confidence.decision_score.toFixed(0)}
                </strong>
              </li>
            )}
            {routing && (
              <li>{outcomeLabel(routing.tier, response.escalated)}</li>
            )}
            <li className="tabular">
              {response.total_latency_ms.toFixed(0)} ms
            </li>
            {response.total_tokens > 0 && (
              <li className="tabular">{response.total_tokens} tokens</li>
            )}
          </ul>

          {response.escalated && (
            <p className="mt-5 border-l-2 border-signal bg-offset px-5 py-3 text-caption">
              A colleague is reviewing this before it reaches you
              {(() => {
                const reason = escalationReason(response.spans);
                if (reason) return ` — ${reason}.`;
                // Only fall back to the routing rationale when routing is
                // what escalated it; otherwise it describes a decision that
                // was overtaken by events.
                return routing?.tier === "human" && routing.rationale
                  ? ` — ${routing.rationale}`
                  : ".";
              })()}
            </p>
          )}

          {response.awaiting && !response.escalated && (
            <p className="mt-5 text-caption text-ink-faint">
              Waiting on: {response.awaiting.replace(/_/g, " ")}
            </p>
          )}

          {response.chunks.length > 0 && <Sources chunks={response.chunks} />}
        </>
      )}
    </article>
  );
}

/**
 * What actually happened to this reply.
 *
 * `routing.tier` alone is not the answer. Routing is decided before the
 * reply is written, so a draft that scores 91 is tiered `auto` and only
 * fails its grounding check afterwards — leaving the tier saying
 * "answered automatically" on a message that went to a person. The
 * escalation flag is set later and is the one that reflects the outcome.
 */
function outcomeLabel(tier: string, escalated: boolean): string {
  if (escalated) return "Passed to a person";
  if (tier === "auto") return "Answered automatically";
  if (tier === "premium") return "Reviewed by the premium model";
  return "Passed to a person";
}

const ESCALATION_REASONS: Record<string, string> = {
  low_confidence: "the confidence score was too low to answer automatically",
  grounding_failed: "the drafted reply could not be traced to our documents",
  complaint: "it was read as a complaint",
  negative_sentiment: "the message reads as frustrated",
  unsupported_financial_claim: "the draft quoted a figure no tool produced",
  policy_requires_approval: "policy requires a person to approve this",
  previously_human_handled: "a colleague is already handling this conversation",
  awaiting_operator_reply: "a colleague is already handling this conversation",
};

/**
 * Why it went to a person, in the customer's language.
 *
 * Prefers the recorded escalation reason over `routing.rationale`, which
 * explains the *score band* and reads as a contradiction when a
 * high-scoring reply is escalated for an unrelated reason — "Score 91
 * clears the automatic threshold" printed directly beneath "a colleague is
 * reviewing this".
 */
function escalationReason(spans: Span[]): string | null {
  const span = spans.find((s) => s.node === "escalate_human");
  const reason = span?.attributes?.reason;
  return typeof reason === "string" ? ESCALATION_REASONS[reason] ?? null : null;
}

/**
 * The provenance panel.
 *
 * Collapsed by default so the answer stays clean, but every score from every
 * retrieval stage is one click away. Showing all four — rather than only the
 * final ranking — is what lets a surprising result be explained: "BM25 found
 * this, the dense model did not" is a real and useful thing to be able to see.
 */
function Sources({ chunks }: { chunks: Chunk[] }) {
  const [open, setOpen] = useState(false);

  return (
    <section className="mt-7">
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        className="label transition-colors hover:text-ink"
      >
        {open ? "Hide" : "Show"} sources ({chunks.length})
      </button>

      {open && (
        <div className="mt-5 space-y-px bg-rule">
          {chunks.map((chunk) => (
            <SourceCard key={chunk.chunk_id} chunk={chunk} />
          ))}
        </div>
      )}
    </section>
  );
}

function SourceCard({ chunk }: { chunk: Chunk }) {
  const [expanded, setExpanded] = useState(false);
  const rtl = isArabic(chunk.text);

  return (
    <div className="bg-paper p-5">
      <button
        type="button"
        onClick={() => setExpanded((value) => !value)}
        className="flex w-full items-baseline justify-between gap-4 text-left"
      >
        <span className="font-mono text-caption text-ink">
          {chunk.source}
          {chunk.page !== null && (
            <span className="text-ink-faint"> · p.{chunk.page}</span>
          )}
        </span>
        <span className="label shrink-0">
          {expanded ? "Less" : "More"}
        </span>
      </button>

      <p
        dir={rtl ? "rtl" : "ltr"}
        className={`mt-3 text-caption text-ink-muted ${expanded ? "" : "line-clamp-2"}`}
      >
        {chunk.text}
      </p>

      {expanded && (
        <>
          <dl className="mt-5 grid grid-cols-2 gap-px border border-rule bg-rule sm:grid-cols-4">
            {[
              ["Dense", chunk.dense_score],
              ["BM25", chunk.bm25_score],
              ["Fused", chunk.rrf_score],
              ["Reranked", chunk.rerank_score],
            ].map(([label, score]) => (
              <div key={label as string} className="bg-paper px-4 py-3">
                <dt className="label">{label as string}</dt>
                <dd className="tabular mt-1 font-mono text-caption">
                  {fmt(score as number | null)}
                </dd>
              </div>
            ))}
          </dl>

          <p className="mt-3 text-caption text-ink-faint">
            {chunk.collection}
            {chunk.rank_delta !== null && chunk.rank_delta !== 0 && (
              <>
                {" · "}
                reranking moved this{" "}
                {chunk.rank_delta < 0 ? "up" : "down"}{" "}
                {Math.abs(chunk.rank_delta)}
                {" places"}
              </>
            )}
            {chunk.authority === "real_uae_regulatory" && (
              <span className="ml-2 text-ink-muted">
                · Real UAE regulatory document
              </span>
            )}
          </p>
        </>
      )}
    </div>
  );
}
