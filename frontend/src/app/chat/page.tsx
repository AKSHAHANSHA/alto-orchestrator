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
import { SiteHeader } from "@/components/SiteHeader";
import { Lumo, LumoMark } from "@/components/Lumo";

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
 *
 * The shell is the LUMO layout: a cream history panel on the left, and a
 * fixed-height chat container on the right that owns its own scroll. The
 * transcript scrolls; the greeting, the composer and the page itself do not.
 * That is the difference between a chat product and a long web page with an
 * input at the bottom.
 */

const EXAMPLES = [
  {
    text: "I want to trade in my old Karva SUV and also check financing for a new Renzo S5 — and can I test drive it Saturday?",
    hint: "Three requests at once",
  },
  { text: "is this still available?", hint: "Deliberately vague" },
  { text: "كم القسط الشهري لسيارة رينزو 2020؟", hint: "Arabic" },
  {
    text: "This is unacceptable, I have been waiting for weeks.",
    hint: "Goes straight to a person",
  },
];

const CONVERSATION_KEY = "alto:conversation_id";
const HISTORY_KEY = "alto:conversations";

interface Turn {
  role: "customer" | "assistant" | "system";
  text: string;
  arabic?: string | null;
  response?: InquiryResponse;
}

/** One row in the sidebar. Titles are derived from the opening message. */
interface HistoryEntry {
  id: string;
  title: string;
  updated: number;
}

function isArabic(text: string): boolean {
  return /[؀-ۿ]/.test(text);
}

function readHistory(): HistoryEntry[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = window.localStorage.getItem(HISTORY_KEY);
    const parsed: unknown = raw ? JSON.parse(raw) : [];
    if (!Array.isArray(parsed)) return [];
    return (parsed as HistoryEntry[])
      .filter((entry) => typeof entry?.id === "string")
      .sort((a, b) => b.updated - a.updated);
  } catch {
    return [];
  }
}

function writeHistory(entries: HistoryEntry[]) {
  if (typeof window === "undefined") return;
  // Twenty is more than anyone scrolls and keeps the key small.
  window.localStorage.setItem(HISTORY_KEY, JSON.stringify(entries.slice(0, 20)));
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
  const [history, setHistory] = useState<HistoryEntry[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const conversationId = useRef<string | undefined>(undefined);
  const scrollRef = useRef<HTMLDivElement>(null);

  // Restore the session on mount. If the browser has a conversation id, ask
  // the server for its transcript — that survives page reloads, navigating
  // to the operations view and back, and any assistant replies an operator
  // composed after a handoff.
  const restore = useCallback(async () => {
    if (typeof window === "undefined") return;
    setHistory(readHistory());

    const stored = window.localStorage.getItem(CONVERSATION_KEY);
    if (!stored) return;
    conversationId.current = stored;
    setActiveId(stored);

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
      setActiveId(null);
      setHistory((prev) => {
        const next = prev.filter((entry) => entry.id !== stored);
        writeHistory(next);
        return next;
      });
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

  // Keep the newest message in view. The transcript owns the scroll box, so
  // this never moves the page itself. Skipped while the greeting is showing —
  // scrolling an empty state to its bottom hides the mascot and the heading,
  // which is the first thing anyone sees.
  useEffect(() => {
    if (turns.length === 0) return;
    const node = scrollRef.current;
    if (node) node.scrollTo({ top: node.scrollHeight, behavior: "smooth" });
  }, [turns.length, busy, calendarPrompt]);

  const remember = useCallback((id: string, firstMessage: string) => {
    setHistory((prev) => {
      const existing = prev.find((entry) => entry.id === id);
      const title =
        existing?.title ??
        (firstMessage.length > 46
          ? `${firstMessage.slice(0, 46).trimEnd()}…`
          : firstMessage);
      const next = [
        { id, title, updated: Date.now() },
        ...prev.filter((entry) => entry.id !== id),
      ];
      writeHistory(next);
      return next;
    });
  }, []);

  async function send(message: string) {
    if (!message.trim() || busy) return;

    setBusy(true);
    setError(null);
    setDraft("");
    setTurns((prev) => [...prev, { role: "customer", text: message }]);

    try {
      const response = await api.submitInquiry(message, conversationId.current);
      conversationId.current = response.conversation_id;
      setActiveId(response.conversation_id);
      if (typeof window !== "undefined") {
        window.localStorage.setItem(CONVERSATION_KEY, response.conversation_id);
      }
      remember(response.conversation_id, message);

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
    setActiveId(null);
    setTurns([]);
    setAwaitingHuman(false);
    setError(null);
    setCalendarPrompt(null);
    setDraft("");
  }

  // Reopening a past conversation. The server is the source of truth for the
  // transcript; a row the server no longer knows about is dropped from the
  // list rather than left to fail again on the next click.
  async function openConversation(id: string) {
    if (busy || id === activeId) return;
    setError(null);
    setCalendarPrompt(null);
    try {
      const state = await api.getConversation(id);
      conversationId.current = id;
      setActiveId(id);
      if (typeof window !== "undefined") {
        window.localStorage.setItem(CONVERSATION_KEY, id);
      }
      setTurns(
        state.transcript.map((turn) => ({
          role: (turn.role as Turn["role"]) ?? "assistant",
          text: turn.text,
        })),
      );
      setAwaitingHuman(state.human_handled);
    } catch {
      setHistory((prev) => {
        const next = prev.filter((entry) => entry.id !== id);
        writeHistory(next);
        return next;
      });
      setError("That conversation is no longer on the server.");
    }
  }

  function handleBooked(confirmation: string) {
    setCalendarPrompt(null);
    setTurns((prev) => [...prev, { role: "assistant", text: confirmation }]);
  }

  const empty = turns.length === 0;

  return (
    /* The chat shell owns the viewport: the page itself never scrolls, the
       transcript does. `dvh` rather than `vh` so a mobile URL bar sliding in
       and out doesn't leave the composer stranded off-screen. */
    <div className="flex h-dvh flex-col overflow-hidden bg-canvas">
      <SiteHeader
        eyebrow="Assistant"
        links={[
          { href: "/workflow", label: "How it works" },
          { href: "/admin", label: "Operations" },
        ]}
        right={
          <button
            type="button"
            onClick={newConversation}
            className="btn-ghost md:hidden"
          >
            New chat
          </button>
        }
      />

      <div className="grid-field min-h-0 flex-1 gap-y-5 py-5 md:py-6">
        {/* ── History panel ──────────────────────────────────────── */}
        <aside className="col-span-4 hidden min-h-0 md:col-span-3 md:block">
          <HistoryPanel
            entries={history}
            activeId={activeId}
            onNew={newConversation}
            onOpen={openConversation}
          />
        </aside>

        {/* ── Chat container ─────────────────────────────────────── */}
        <section className="col-span-4 min-h-0 md:col-span-9">
          <div className="flex h-full flex-col overflow-hidden rounded-chat border border-rule bg-paper shadow-soft">
            <div
              ref={scrollRef}
              className="scroll-warm flex-1 overflow-y-auto px-5 py-8 md:px-10 md:py-10"
            >
              {/* `safe center` keeps the greeting optically centred while it
                  fits, and falls back to top-aligned the moment it doesn't —
                  plain `center` pushes the mascot off the top of the scroll
                  box with no way to reach it. */}
              <div
                className={`mx-auto flex w-full max-w-chat flex-col ${
                  empty ? "min-h-full [justify-content:safe_center]" : ""
                }`}
              >
                {empty ? (
                  <Greeting onPick={send} />
                ) : (
                  <div className="space-y-7">
                    {awaitingHuman && <HumanBanner />}

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

                    {busy && <Thinking />}
                  </div>
                )}

                {error && (
                  <p className="mt-6 rounded-2xl border border-signal/25 bg-signal/[0.06] px-5 py-4 text-small text-signal">
                    {error}
                  </p>
                )}
              </div>
            </div>

            {/* ── Composer ─────────────────────────────────────── */}
            <div className="border-t border-brand-edge bg-brand-soft px-4 py-4 md:px-8 md:py-5">
              <form
                onSubmit={(event) => {
                  event.preventDefault();
                  void send(draft);
                }}
                className="mx-auto w-full max-w-chat"
              >
                <div className="flex items-center gap-2 rounded-chat border border-brand-edge bg-paper p-1.5 pl-4 shadow-soft transition-colors focus-within:border-brand">
                  <input
                    value={draft}
                    onChange={(event) => setDraft(event.target.value)}
                    placeholder="Ask LUMO about a car, financing, a trade-in…"
                    disabled={busy}
                    dir={isArabic(draft) ? "rtl" : "ltr"}
                    className="min-w-0 flex-1 bg-transparent py-2.5 text-small text-ink outline-none placeholder:text-ink-faint disabled:opacity-50"
                  />
                  <button
                    type="submit"
                    disabled={busy || !draft.trim()}
                    aria-label="Send message"
                    className="flex h-11 w-11 shrink-0 items-center justify-center rounded-[20px] bg-brand text-white transition-all duration-200 hover:bg-[#d97c00] disabled:pointer-events-none disabled:opacity-30"
                  >
                    <SendIcon />
                  </button>
                </div>
                <p className="mt-2.5 px-1 text-caption text-ink-warm">
                  LUMO answers from Alto Motors documents and the live catalog.
                  Figures are indicative until a consultant confirms them.
                </p>
              </form>
            </div>
          </div>
        </section>
      </div>
    </div>
  );
}

/* ── Sidebar ─────────────────────────────────────────────────────────────── */

function HistoryPanel({
  entries,
  activeId,
  onNew,
  onOpen,
}: {
  entries: HistoryEntry[];
  activeId: string | null;
  onNew: () => void;
  onOpen: (id: string) => void;
}) {
  return (
    /* The panel is as tall as the row and never taller — the list inside it
       takes whatever is left after the header, the button and the footer
       link, and scrolls on its own. */
    <div className="flex max-h-full flex-col overflow-hidden rounded-panel border border-brand-edge bg-brand-soft shadow-soft">
      <div className="shrink-0 border-b border-white/10 bg-plum-head px-5 py-4">
        <p className="text-label font-bold text-white">
          Your conversation history
        </p>
      </div>

      <div className="flex min-h-0 flex-1 flex-col p-4">
        <button
          type="button"
          onClick={onNew}
          className="flex w-full shrink-0 items-center gap-2 rounded-btn border border-brand-edge bg-paper px-4 py-3 text-label font-bold text-brand-deep transition-all duration-200 hover:border-brand hover:shadow-soft"
        >
          <PlusIcon />
          New chat
        </button>

        <div className="scroll-warm mt-4 min-h-0 flex-1 space-y-1 overflow-y-auto pr-1">
          {entries.length === 0 ? (
            <div className="px-1 py-6 text-center">
              <Lumo pose="sleep" size={92} className="mx-auto" />
              <p className="mt-2 text-caption text-ink-warm">
                No conversations yet.
              </p>
            </div>
          ) : (
            entries.map((entry) => {
              const active = entry.id === activeId;
              return (
                <button
                  key={entry.id}
                  type="button"
                  onClick={() => onOpen(entry.id)}
                  title={entry.title}
                  className={`block w-full truncate rounded-lg px-3 py-2.5 text-left text-caption transition-colors ${
                    active
                      ? "bg-paper font-semibold text-brand-deep shadow-soft"
                      : "text-ink-warm hover:bg-white/60"
                  }`}
                >
                  {entry.title}
                </button>
              );
            })
          )}
        </div>
      </div>

      <div className="shrink-0 border-t border-brand-edge/70 px-5 py-4">
        <Link
          href="/workflow"
          className="text-caption text-ink-warm transition-colors hover:text-brand-deep"
        >
          How LUMO decides →
        </Link>
      </div>
    </div>
  );
}

/* ── Empty state ─────────────────────────────────────────────────────────── */

function Greeting({ onPick }: { onPick: (text: string) => void }) {
  return (
    <div className="py-6">
      <div className="flex flex-col items-center text-center">
        <div className="relative">
          <div
            className="glow-brand pointer-events-none absolute -inset-16"
            aria-hidden
          />
          <Lumo pose="wave" size={128} float priority className="relative" />
        </div>
        <h1 className="mt-4 text-greeting font-semibold text-plum">
          Hello, I&rsquo;m <span className="text-brand">LUMO</span>
        </h1>
        <p className="mt-3 max-w-xl text-small text-ink-muted">
          Ask about a vehicle, financing, a trade-in or a test drive — in
          English or Arabic. Mixing several questions into one message is
          fine; that is what I am built for.
        </p>
      </div>

      <p className="label mb-3 mt-9">Try one of these</p>
      <div className="grid gap-3 sm:grid-cols-2">
        {EXAMPLES.map((example) => (
          <button
            key={example.text}
            type="button"
            onClick={() => onPick(example.text)}
            dir={isArabic(example.text) ? "rtl" : "ltr"}
            className="card card-hover rounded-3xl p-4 text-left"
          >
            <span className="chip bg-brand-soft text-brand-deep">
              {example.hint}
            </span>
            <span className="mt-2 block text-caption text-ink">
              {example.text}
            </span>
          </button>
        ))}
      </div>
    </div>
  );
}

function HumanBanner() {
  return (
    <div className="flex items-start gap-3 rounded-3xl border border-plum/15 bg-plum-tint px-5 py-4">
      <span className="mt-0.5 h-2 w-2 shrink-0 rounded-full bg-plum-soft" aria-hidden />
      <p className="text-small text-plum">
        A member of our team is handling this conversation. Their reply will
        appear here shortly.
      </p>
    </div>
  );
}

function Thinking() {
  return (
    <div className="flex items-center gap-3">
      <LumoMark size={32} className="shrink-0" />
      <div className="flex items-center gap-1.5 rounded-3xl rounded-tl-md bg-offset px-5 py-4">
        {[0, 1, 2].map((index) => (
          <span
            key={index}
            className="h-1.5 w-1.5 animate-dot-bounce rounded-full bg-brand"
            style={{ animationDelay: `${index * 160}ms` }}
          />
        ))}
        <span className="sr-only">LUMO is thinking</span>
      </div>
    </div>
  );
}

/* ── Turns ───────────────────────────────────────────────────────────────── */

function CustomerTurn({ text }: { text: string }) {
  const rtl = isArabic(text);
  return (
    <div className="flex animate-rise-in justify-end">
      <p
        dir={rtl ? "rtl" : "ltr"}
        className="max-w-[85%] rounded-3xl rounded-br-md bg-plum px-5 py-3.5 text-small text-white"
      >
        {text}
      </p>
    </div>
  );
}

function SystemTurn({ text }: { text: string }) {
  return (
    <p className="text-center text-caption italic text-ink-faint">{text}</p>
  );
}

function AssistantTurn({ turn }: { turn: Turn }) {
  const response = turn.response;
  const routing = response?.routing;
  const rtl = isArabic(turn.text);

  return (
    <article className="flex animate-rise-in gap-3">
      <LumoMark size={32} className="mt-1 shrink-0" />

      <div className="min-w-0 flex-1">
        <div className="rounded-3xl rounded-tl-md border border-brand-edge bg-brand-soft px-5 py-4">
          <p dir={rtl ? "rtl" : "ltr"} className="text-small text-ink">
            {turn.text}
          </p>

          {turn.arabic && (
            <p
              dir="rtl"
              className="mt-4 border-t border-brand-edge pt-4 text-small text-ink"
            >
              {turn.arabic}
            </p>
          )}
        </div>

        {response && (
          <>
            <ul className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-2 px-1 text-caption text-ink-faint">
              {response.confidence && (
                <li className="tabular">
                  Confidence{" "}
                  <strong className="font-semibold text-plum">
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
              <p className="mt-3 rounded-2xl border border-signal/20 bg-signal/[0.05] px-4 py-3 text-caption text-ink-muted">
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
              <p className="mt-2 px-1 text-caption text-ink-faint">
                Waiting on: {response.awaiting.replace(/_/g, " ")}
              </p>
            )}

            {response.chunks.length > 0 && <Sources chunks={response.chunks} />}
          </>
        )}
      </div>
    </article>
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

/* ── Provenance ──────────────────────────────────────────────────────────── */

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
    <section className="mt-3">
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        className="inline-flex items-center gap-1.5 rounded-full bg-plum-tint px-3 py-1.5 text-caption font-semibold text-plum transition-colors hover:bg-plum/10"
      >
        <Chevron open={open} />
        {open ? "Hide" : "Show"} sources ({chunks.length})
      </button>

      {open && (
        <div className="mt-3 space-y-2">
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
    <div className="card rounded-2xl p-4">
      <button
        type="button"
        onClick={() => setExpanded((value) => !value)}
        className="flex w-full items-baseline justify-between gap-4 text-left"
      >
        <span className="truncate font-mono text-caption text-plum">
          {chunk.source}
          {chunk.page !== null && (
            <span className="text-ink-faint"> · p.{chunk.page}</span>
          )}
        </span>
        <span className="shrink-0 text-caption font-semibold text-brand-deep">
          {expanded ? "Less" : "More"}
        </span>
      </button>

      <p
        dir={rtl ? "rtl" : "ltr"}
        className={`mt-2 text-caption text-ink-muted ${expanded ? "" : "line-clamp-2"}`}
      >
        {chunk.text}
      </p>

      {expanded && (
        <>
          <dl className="mt-4 grid grid-cols-2 gap-2 sm:grid-cols-4">
            {[
              ["Dense", chunk.dense_score],
              ["BM25", chunk.bm25_score],
              ["Fused", chunk.rrf_score],
              ["Reranked", chunk.rerank_score],
            ].map(([label, score]) => (
              <div
                key={label as string}
                className="rounded-lg bg-offset px-3 py-2"
              >
                <dt className="label-muted">{label as string}</dt>
                <dd className="tabular mt-1 font-mono text-caption text-ink">
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
              <span className="ml-2 text-brand-deep">
                · Real UAE regulatory document
              </span>
            )}
          </p>
        </>
      )}
    </div>
  );
}

/* ── Icons ───────────────────────────────────────────────────────────────── */

function SendIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden>
      <path
        d="M4 12h14M12 5l7 7-7 7"
        stroke="currentColor"
        strokeWidth="2.2"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function PlusIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" aria-hidden>
      <path
        d="M12 5v14M5 12h14"
        stroke="currentColor"
        strokeWidth="2.6"
        strokeLinecap="round"
      />
    </svg>
  );
}

function Chevron({ open }: { open: boolean }) {
  return (
    <svg
      width="12"
      height="12"
      viewBox="0 0 24 24"
      fill="none"
      aria-hidden
      className={`transition-transform duration-200 ${open ? "rotate-90" : ""}`}
    >
      <path
        d="M9 6l6 6-6 6"
        stroke="currentColor"
        strokeWidth="2.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}
