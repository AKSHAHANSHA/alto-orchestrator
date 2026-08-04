"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  api,
  API_BASE,
  type Booking,
  type Confidence,
  type Metrics,
  type ReviewItem,
  type TranscriptTurn,
} from "@/lib/api";
import { SiteHeader } from "@/components/SiteHeader";
import { LumoMark } from "@/components/Lumo";

/**
 * Operations view.
 *
 * Built around the question a coordinator actually asks — "why did it do
 * that?" — rather than around vanity metrics. Every review item is
 * presented as a chat window: transcript above (scrollable), reply input
 * pinned to the bottom of the window. Whole conversation, whole time, no
 * hunting.
 *
 * Once a conversation is handed to a person, the operator can keep replying
 * from here without a new review item per turn — the graph steps aside and
 * the transcript is the shared channel.
 *
 * This is a working surface, not a marketing page, so the warm cream is used
 * sparingly — it marks where LUMO is speaking and where the operator types,
 * and everything else stays on white so the data reads first.
 */

const REFRESH_MS = 4000;
const REVIEWER = "coordinator@alto";

const DEPARTMENTS: Array<{ id: string; label: string }> = [
  { id: "sales", label: "Sales" },
  { id: "finance", label: "Finance" },
  { id: "trade_in", label: "Trade-In" },
  { id: "service", label: "Service" },
  { id: "customer_relations", label: "Customer relations" },
];

export default function AdminPage() {
  const [metrics, setMetrics] = useState<Metrics | null>(null);
  const [queue, setQueue] = useState<ReviewItem[]>([]);
  const [appointments, setAppointments] = useState<Booking[]>([]);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const [nextMetrics, nextQueue, nextAppointments] = await Promise.all([
        api.metrics(),
        api.humanQueue(),
        api.listAppointments(),
      ]);
      setMetrics(nextMetrics);
      setQueue(nextQueue);
      setAppointments(nextAppointments.appointments);
      setError(null);
    } catch (exception) {
      setError(
        exception instanceof Error
          ? exception.message
          : "Could not reach the orchestrator.",
      );
    }
  }, []);

  useEffect(() => {
    void load();
    const timer = setInterval(() => void load(), REFRESH_MS);
    return () => clearInterval(timer);
  }, [load]);

  return (
    <div className="min-h-screen bg-canvas">
      <SiteHeader
        eyebrow="Operations"
        links={[{ href: "/chat", label: "Customer view" }]}
        right={
          metrics && (
            <span className="hidden items-center gap-2 rounded-full bg-plum-tint px-3 py-1.5 text-caption text-plum lg:inline-flex">
              <span
                className={`h-1.5 w-1.5 rounded-full ${
                  metrics.retrieval_enabled ? "bg-positive" : "bg-ink-faint"
                }`}
                aria-hidden
              />
              {metrics.provider} ·{" "}
              {metrics.retrieval_enabled ? "retrieval on" : "retrieval off"}
            </span>
          )
        }
      />

      <main className="grid-field py-8 md:py-10">
        {error && (
          <div className="col-span-4 mb-8 rounded-3xl border border-signal/25 bg-signal/[0.05] px-6 py-5 md:col-span-12">
            <p className="text-small font-semibold text-signal">{error}</p>
            <p className="mt-1 text-caption text-ink-muted">
              The frontend is trying to reach{" "}
              <code className="rounded bg-paper px-1.5 py-0.5 font-mono">
                {API_BASE}
              </code>
              . Is the backend running there?
            </p>
          </div>
        )}

        {/* ── Headline numbers ─────────────────────────────────── */}
        <section className="col-span-4 md:col-span-12">
          <h1 className="text-headline font-semibold text-plum">
            Live operations
          </h1>
          <dl className="mt-6 grid grid-cols-2 gap-3 md:grid-cols-3 lg:grid-cols-6">
            {[
              ["Conversations", metrics?.conversations ?? "—"],
              ["Awaiting review", metrics?.open_reviews ?? "—"],
              ["Bookings", appointments.length],
              [
                "Avg latency",
                metrics ? `${metrics.avg_latency_ms.toFixed(0)} ms` : "—",
              ],
              ["Tokens", metrics?.total_tokens ?? "—"],
              [
                "Spend",
                metrics ? `$${metrics.total_cost_usd.toFixed(4)}` : "—",
              ],
            ].map(([label, value]) => (
              <div key={label as string} className="card rounded-2xl px-5 py-5">
                <dt className="label-muted">{label as string}</dt>
                <dd className="tabular mt-2 text-title font-semibold text-plum">
                  {value as string | number}
                </dd>
              </div>
            ))}
          </dl>
        </section>

        {/* ── Human queue ──────────────────────────────────────── */}
        <section className="col-span-4 mt-12 md:col-span-8">
          <div className="flex items-baseline justify-between">
            <h2 className="text-title font-semibold text-plum">Human queue</h2>
            <span
              className={`chip ${
                queue.length > 0
                  ? "bg-brand-soft text-brand-deep"
                  : "bg-plum-tint text-plum"
              }`}
            >
              {queue.length} open
            </span>
          </div>

          {queue.length === 0 ? (
            <div className="card mt-5 rounded-3xl px-6 py-12 text-center">
              <p className="text-small text-ink-muted">
                Nothing waiting. Escalations appear here the moment a
                conversation falls below the confidence threshold or trips a
                hard override.
              </p>
            </div>
          ) : (
            <div className="mt-5 space-y-6">
              {queue.map((item) => (
                <ReviewCard key={item.id} item={item} onDone={load} />
              ))}
            </div>
          )}
        </section>

        {/* ── Bookings + performance ───────────────────────────── */}
        <section className="col-span-4 mt-12 md:col-span-4">
          <h2 className="text-title font-semibold text-plum">
            Recent test-drive bookings
          </h2>
          <div className="mt-5 space-y-2">
            {appointments.length === 0 ? (
              <p className="card rounded-2xl px-5 py-6 text-caption text-ink-faint">
                No test-drive bookings yet.
              </p>
            ) : (
              appointments.map((booking) => (
                <article
                  key={booking.id}
                  className="rounded-2xl border border-positive/20 bg-positive/[0.06] px-5 py-4"
                >
                  <p className="label-muted !text-positive">Test drive booked</p>
                  <p className="mt-1.5 text-small font-semibold text-plum">
                    {booking.vehicle}
                  </p>
                  <p className="tabular mt-1 font-mono text-caption text-ink-muted">
                    {booking.slot_label}
                  </p>
                  <p className="mt-1 truncate font-mono text-caption text-ink-faint">
                    {booking.conversation_id.slice(0, 18)}…
                  </p>
                </article>
              ))
            )}
          </div>

          <h2 className="mt-10 text-title font-semibold text-plum">By layer</h2>
          <div className="card mt-5 divide-y divide-rule rounded-2xl">
            {(metrics?.by_layer ?? []).map((layer) => (
              <div
                key={layer.layer}
                className="flex items-baseline justify-between px-5 py-3"
              >
                <span className="text-caption capitalize text-ink">
                  {layer.layer}
                </span>
                <span className="tabular font-mono text-caption text-ink-muted">
                  {layer.latency_ms.toFixed(0)} ms · {layer.calls}
                </span>
              </div>
            ))}
            {!metrics?.by_layer.length && (
              <p className="px-5 py-6 text-caption text-ink-faint">
                No traffic yet.
              </p>
            )}
          </div>
        </section>
      </main>
    </div>
  );
}

function isArabic(text: string): boolean {
  return /[؀-ۿ]/.test(text);
}

// The backend pre-formats slot labels in dealer local time. Do not reformat
// them here — the browser's local timezone gave "15:30 PM" for what the
// backend called "10:00", which is the exact bug the pre-formatted labels
// exist to prevent.

/**
 * One review card, presented as a full chat window.
 *
 * Scrollable transcript with a fixed input at the bottom — the operator
 * scrolls up to see history, types at the bottom without losing the input to
 * a growing message list. Confidence bars, rationale, and the
 * resolve/reassign actions sit below the conversation so nothing crowds it.
 */
function ReviewCard({ item, onDone }: { item: ReviewItem; onDone: () => void }) {
  const [replyText, setReplyText] = useState("");
  const [reassignTo, setReassignTo] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showRouting, setShowRouting] = useState(false);
  const transcriptRef = useRef<HTMLDivElement>(null);

  // Whenever new turns arrive from polling, scroll the transcript to the
  // bottom — same behaviour as any real chat client. The operator is
  // reading toward the newest message, not the oldest.
  useEffect(() => {
    const node = transcriptRef.current;
    if (node) node.scrollTop = node.scrollHeight;
  }, [item.transcript.length]);

  async function resolve(
    outcome: "approved" | "edited" | "reassigned" | "rejected",
    options: { finalText?: string; reassignTo?: string } = {},
  ) {
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      await api.resolveReview(item.id, outcome, REVIEWER, options);
      setReplyText("");
      onDone();
    } catch (exception) {
      setError(exception instanceof Error ? exception.message : "Could not resolve.");
    } finally {
      setBusy(false);
    }
  }

  async function sendReply() {
    if (!replyText.trim() || busy) return;
    // First reply against a review with a draft gets treated as "edited"
    // (deliver the operator's text instead of the draft). After the review
    // is resolved, subsequent replies use the live endpoint.
    if (item.is_open) {
      await resolve("edited", { finalText: replyText.trim() });
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await api.humanReply(item.conversation_id, replyText.trim(), REVIEWER);
      setReplyText("");
      onDone();
    } catch (exception) {
      setError(exception instanceof Error ? exception.message : "Could not send.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <article className="overflow-hidden rounded-panel border border-rule bg-paper shadow-soft">
      <header className="flex flex-wrap items-center justify-between gap-3 bg-plum px-5 py-4">
        <div className="min-w-0">
          <p className="text-small font-semibold capitalize text-white">
            {item.reason.replace(/_/g, " ")}
          </p>
          <p className="mt-1 truncate font-mono text-caption text-white/50">
            {item.conversation_id} · {item.department ?? "unassigned"}
          </p>
        </div>
        {item.routing && (
          <button
            type="button"
            onClick={() => setShowRouting((v) => !v)}
            className="shrink-0 rounded-full border border-white/20 px-3 py-1.5 text-caption text-white/75 transition-colors hover:border-brand hover:text-brand"
          >
            {showRouting ? "Hide" : "Show"} routing
          </button>
        )}
      </header>

      {/* ── Chat window: scrollable transcript, pinned input ────────── */}
      <div className="flex h-[440px] flex-col bg-paper">
        <div
          ref={transcriptRef}
          className="scroll-warm flex-1 space-y-3 overflow-y-auto px-5 py-5"
        >
          <Transcript turns={item.transcript} />
        </div>

        <div className="border-t border-brand-edge bg-brand-soft px-5 py-4">
          {item.draft && (
            <details className="mb-3">
              <summary className="cursor-pointer text-caption font-semibold text-brand-deep">
                Suggested draft
              </summary>
              <p className="mt-2 text-caption text-ink-warm">{item.draft.en}</p>
              {item.draft.ar && (
                <p dir="rtl" className="mt-2 text-caption text-ink-warm">
                  {item.draft.ar}
                </p>
              )}
              <button
                type="button"
                onClick={() => setReplyText(item.draft?.en ?? "")}
                className="mt-2 text-caption font-semibold text-brand-deep hover:underline"
              >
                Use this draft
              </button>
            </details>
          )}

          <div className="flex items-center gap-2 rounded-2xl border border-brand-edge bg-paper p-1.5 pl-4 transition-colors focus-within:border-brand">
            <input
              value={replyText}
              onChange={(event) => setReplyText(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter" && !event.shiftKey) {
                  event.preventDefault();
                  void sendReply();
                }
              }}
              placeholder="Type your reply to the customer…"
              dir={isArabic(replyText) ? "rtl" : "ltr"}
              disabled={busy}
              className="min-w-0 flex-1 bg-transparent py-2 text-small text-ink outline-none placeholder:text-ink-faint disabled:opacity-50"
            />
            <button
              type="button"
              onClick={() => void sendReply()}
              disabled={busy || !replyText.trim()}
              className="shrink-0 rounded-xl bg-brand px-4 py-2 text-caption font-semibold text-white transition-colors hover:bg-[#d97c00] disabled:pointer-events-none disabled:opacity-30"
            >
              Send
            </button>
          </div>

          {error && (
            <p className="mt-3 rounded-xl border border-signal/25 bg-paper px-3 py-2 text-caption text-signal">
              {error}
            </p>
          )}
        </div>
      </div>

      {/* ── Metadata: confidence, routing, and close actions ────────── */}
      <div className="grid divide-y divide-rule border-t border-rule md:grid-cols-2 md:divide-x md:divide-y-0">
        <div className="p-5">
          {item.confidence ? (
            <ConfidenceBars confidence={item.confidence} />
          ) : (
            <p className="text-caption text-ink-faint">
              No confidence vector for this handoff.
            </p>
          )}
          {item.routing && (
            <p className="mt-4 text-caption text-ink-muted">
              {item.routing.rationale}
            </p>
          )}
          {showRouting && item.routing && (
            <pre className="mt-4 overflow-x-auto rounded-xl border border-rule bg-offset p-3 font-mono text-[11px] leading-relaxed text-ink-muted">
              {JSON.stringify(item.routing, null, 2)}
            </pre>
          )}
        </div>

        <div className="p-5">
          <p className="label-muted mb-3">Close or reassign</p>
          <div className="space-y-2">
            {item.is_open && item.draft && (
              <button
                type="button"
                onClick={() => resolve("approved")}
                disabled={busy}
                className="btn-primary w-full"
              >
                Approve draft &amp; send
              </button>
            )}
            <button
              type="button"
              onClick={() => resolve("rejected")}
              disabled={busy}
              className="btn-ghost w-full"
            >
              Dismiss without sending
            </button>
          </div>

          <div className="mt-5 flex gap-2 border-t border-rule pt-4">
            <select
              value={reassignTo}
              onChange={(event) => setReassignTo(event.target.value)}
              disabled={busy}
              className="field flex-1 py-2.5 text-caption"
            >
              <option value="">Hand to another team…</option>
              {DEPARTMENTS.map((d) => (
                <option key={d.id} value={d.id}>
                  {d.label}
                </option>
              ))}
            </select>
            <button
              type="button"
              onClick={() => resolve("reassigned", { reassignTo })}
              disabled={busy || !reassignTo}
              className="btn-plum shrink-0"
            >
              Reassign
            </button>
          </div>
        </div>
      </div>
    </article>
  );
}

/**
 * The customer's conversation, in order.
 *
 * Rendered in-place inside the scrollable pane — no fixed height of its
 * own, no overflow of its own. Its parent owns the scroll box.
 */
function Transcript({ turns }: { turns: TranscriptTurn[] }) {
  if (turns.length === 0) {
    return (
      <p className="text-caption italic text-ink-faint">
        No transcript recorded for this conversation.
      </p>
    );
  }

  return (
    <>
      {turns.map((turn, index) => {
        const rtl = isArabic(turn.text);
        if (turn.role === "customer") {
          return (
            <div key={index} className="flex justify-end">
              <p
                dir={rtl ? "rtl" : "ltr"}
                className="max-w-[85%] rounded-2xl rounded-br-md bg-plum px-4 py-2.5 text-small text-white"
              >
                {turn.text}
              </p>
            </div>
          );
        }
        if (turn.role === "system") {
          return (
            <p
              key={index}
              className="text-center text-caption italic text-ink-faint"
            >
              {turn.text}
            </p>
          );
        }
        return (
          <div key={index} className="flex gap-2">
            <LumoMark size={24} className="mt-1 shrink-0" />
            <p
              dir={rtl ? "rtl" : "ltr"}
              className="max-w-[85%] rounded-2xl rounded-tl-md border border-brand-edge bg-brand-soft px-4 py-2.5 text-small text-ink"
            >
              {turn.text}
            </p>
          </div>
        );
      })}
    </>
  );
}

/**
 * The six signals, shown separately.
 *
 * The weakest is marked in red — that single annotation is usually the whole
 * explanation for why a conversation escalated.
 */
function ConfidenceBars({ confidence }: { confidence: Confidence }) {
  const signals: Array<[string, number]> = [
    ["language", confidence.language],
    ["intent", confidence.intent],
    ["entity", confidence.entity],
    ["retrieval", confidence.retrieval],
    ["risk", confidence.risk],
    ["policy", confidence.policy],
  ];

  return (
    <div>
      <div className="mb-3 flex items-baseline justify-between">
        <span className="label-muted">Confidence</span>
        <span className="tabular font-mono text-caption text-plum">
          {confidence.decision_score.toFixed(0)} / 100
        </span>
      </div>

      <div className="space-y-2">
        {signals.map(([name, value]) => {
          const weakest = name === confidence.weakest_signal;
          return (
            <div key={name} className="flex items-center gap-3">
              <span
                className={`w-16 shrink-0 text-[11px] ${
                  weakest ? "font-semibold text-signal" : "text-ink-faint"
                }`}
              >
                {name}
              </span>
              <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-rule">
                <div
                  className={`h-full rounded-full transition-all duration-500 ease-soft ${
                    weakest ? "bg-signal" : "bg-brand"
                  }`}
                  style={{ width: `${Math.max(2, value * 100)}%` }}
                />
              </div>
              <span className="tabular w-9 shrink-0 text-right font-mono text-[11px] text-ink-faint">
                {value.toFixed(2)}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
