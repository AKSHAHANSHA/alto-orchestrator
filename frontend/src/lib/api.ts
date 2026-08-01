/**
 * Typed client for the orchestrator API.
 *
 * The shapes here mirror the FastAPI DTOs. They are hand-written rather than
 * generated so the frontend can be read on its own, but they are the same
 * contract — `backend/app/api/v1/schemas.py` is the source of truth.
 */

export const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

export interface Chunk {
  chunk_id: string;
  doc_id: string;
  text: string;
  collection: string;
  source: string | null;
  title: string | null;
  page: number | null;
  authority: string | null;
  dense_score: number | null;
  bm25_score: number | null;
  rrf_score: number | null;
  rerank_score: number | null;
  dense_rank: number | null;
  bm25_rank: number | null;
  fused_rank: number | null;
  final_rank: number | null;
  rank_delta: number | null;
}

export interface Intent {
  id: string;
  category: string;
  status: string;
  confidence: number;
  priority: number;
  is_primary: boolean;
  department: string | null;
  missing_slots: string[];
  depends_on: string[];
  evidence: string | null;
}

export interface Confidence {
  language: number;
  intent: number;
  entity: number;
  retrieval: number;
  risk: number;
  policy: number;
  decision_score: number;
  weakest_signal: string;
}

export interface Routing {
  tier: "auto" | "premium" | "human";
  department: string | null;
  model_tier: string | null;
  rule_id: string;
  rationale: string;
  overrides_applied: string[];
}

export interface Reply {
  en: string;
  ar: string | null;
  is_bilingual: boolean;
  requires_human_approval: boolean;
}

export interface Grounding {
  verdict: string;
  faithfulness_score: number;
  total_claims: number;
  unsupported_claims: number;
  has_unsupported_numeric_claim: boolean;
}

export interface Span {
  node: string;
  layer: string;
  status: string;
  latency_ms: number;
  model: string | null;
  provider: string | null;
  prompt_tokens: number;
  completion_tokens: number;
  cost_usd: number;
  attributes: Record<string, unknown>;
  error: string | null;
}

export interface InquiryResponse {
  conversation_id: string;
  trace_id: string;
  language: Record<string, unknown> | null;
  sentiment: Record<string, unknown> | null;
  intents: Intent[];
  entities: Array<Record<string, unknown>>;
  next_action: string | null;
  plan_steps: Array<Record<string, unknown>>;
  confidence: Confidence | null;
  routing: Routing | null;
  reply: Reply | null;
  grounding: Grounding | null;
  chunks: Chunk[];
  actions: Array<Record<string, unknown>>;
  escalated: boolean;
  awaiting: string | null;
  total_latency_ms: number;
  total_cost_usd: number;
  total_tokens: number;
  spans: Span[];
}

export interface TranscriptTurn {
  role: "customer" | "assistant" | "system" | string;
  text: string;
  at: string;
}

export interface ReviewItem {
  id: string;
  conversation_id: string;
  reason: string;
  department: string | null;
  created_at: string;
  is_open: boolean;
  draft: Reply | null;
  routing: Routing | null;
  confidence: Confidence | null;
  transcript: TranscriptTurn[];
}

export interface ConversationState {
  conversation_id: string;
  customer_id: string | null;
  channel: string;
  human_handled: boolean;
  transcript: TranscriptTurn[];
  open_intents: Array<{
    id: string;
    category: string;
    status: string;
    department: string | null;
    missing_slots: string[];
  }>;
}

export interface Metrics {
  conversations: number;
  open_reviews: number;
  escalation_rate: number;
  total_cost_usd: number;
  total_tokens: number;
  avg_latency_ms: number;
  provider: string;
  budget_remaining_usd: number;
  retrieval_enabled: boolean;
  by_node: Array<{
    node: string;
    calls: number;
    avg_latency_ms: number;
    max_latency_ms: number;
  }>;
  by_layer: Array<{
    layer: string;
    calls: number;
    latency_ms: number;
    cost_usd: number;
  }>;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
  });

  if (!response.ok) {
    // Domain errors carry structured detail; surface it rather than a bare
    // status code, so the UI can say what actually went wrong.
    let detail = response.statusText;
    try {
      const body = await response.json();
      detail = body?.detail?.message ?? body?.message ?? detail;
    } catch {
      /* response had no JSON body */
    }
    throw new Error(detail);
  }

  return response.json() as Promise<T>;
}

export interface Booking {
  id: string;
  conversation_id: string;
  slot_id: string;
  slot_start: string;
  slot_end: string;
  // Pre-formatted, dealer-local. Use these strings verbatim — do NOT
  // reformat slot_start on the client, that reintroduces the timezone bug
  // the backend just fixed.
  day_label: string;
  time_label: string;
  slot_label: string;
  vehicle: string;
  customer_name: string | null;
  contact_phone: string | null;
  created_at: string;
  status: string;
}

export interface CalendarSlot {
  slot_id: string;
  start: string;
  end: string;
  is_available: boolean;
  day_short: string;
  day_number: string;
  month_short: string;
  day_label: string;
  time_label: string;
  iso_date: string;
}

export const api = {
  submitInquiry: (message: string, conversationId?: string) =>
    request<InquiryResponse>("/api/v1/inquiries", {
      method: "POST",
      body: JSON.stringify({
        message,
        conversation_id: conversationId,
        channel: "web_form",
      }),
    }),

  listSlots: (days = 14) =>
    request<{ slots: CalendarSlot[]; horizon_days: number; slot_hours: number }>(
      `/api/v1/appointments/slots?days=${days}`,
    ),

  bookSlot: (params: {
    conversationId: string;
    slotId: string;
    vehicle: string;
    customerName?: string;
    contactPhone?: string;
  }) =>
    request<{ booking: Booking; confirmation: string }>(
      "/api/v1/appointments/book",
      {
        method: "POST",
        body: JSON.stringify({
          conversation_id: params.conversationId,
          slot_id: params.slotId,
          vehicle: params.vehicle,
          customer_name: params.customerName,
          contact_phone: params.contactPhone,
        }),
      },
    ),

  listAppointments: () =>
    request<{ appointments: Booking[] }>("/api/v1/admin/appointments"),

  conversations: () =>
    request<Array<Record<string, unknown>>>("/api/v1/conversations"),

  humanQueue: () => request<ReviewItem[]>("/api/v1/admin/human-queue"),

  getConversation: (conversationId: string) =>
    request<ConversationState>(`/api/v1/conversations/${conversationId}`),

  /**
   * Close a review item.
   *
   * ``approved``  — the drafted reply is delivered to the customer as-is.
   * ``edited``    — ``finalText`` overrides the draft; supply it.
   * ``reassigned``— hand off to ``reassignTo`` (a department id). Does not
   *                 deliver a reply; the receiving team takes over.
   * ``rejected``  — close without delivering anything.
   */
  resolveReview: (
    id: string,
    outcome: string,
    reviewer: string,
    options: { finalText?: string; reassignTo?: string } = {},
  ) =>
    request<Record<string, unknown>>(
      `/api/v1/admin/human-queue/${id}/resolve`,
      {
        method: "POST",
        body: JSON.stringify({
          outcome,
          reviewer,
          final_text: options.finalText,
          reassign_to: options.reassignTo,
        }),
      },
    ),

  /**
   * Send a live message from a human operator into an ongoing conversation.
   * After handoff the customer's next message no longer runs the graph, so
   * this is how follow-ups reach them.
   */
  humanReply: (conversationId: string, text: string, reviewer: string) =>
    request<Record<string, unknown>>(
      `/api/v1/admin/conversations/${conversationId}/reply`,
      { method: "POST", body: JSON.stringify({ text, reviewer }) },
    ),

  metrics: () => request<Metrics>("/api/v1/admin/metrics"),

  trace: (conversationId: string) =>
    request<{ spans: Span[]; total_latency_ms: number; total_cost_usd: number }>(
      `/api/v1/conversations/${conversationId}/trace`,
    ),
};

/** Formats a score for display, tolerating nulls from skipped stages. */
export function fmt(value: number | null | undefined, digits = 3): string {
  if (value === null || value === undefined) return "—";
  return value.toFixed(digits);
}
