"use client";

import { useEffect, useMemo, useState } from "react";
import { api, type CalendarSlot } from "@/lib/api";

/**
 * Two-step slot picker: pick a day, then a 2-hour time slot.
 *
 * Feels more like a real booking page and less like a spreadsheet:
 *   1. A horizontal strip of day cards at the top — day-of-week above,
 *      day-of-month below. The selected day fills with plum.
 *   2. A wrap-flow of time pills below for the selected day. The selected
 *      pill takes the amber accent; unavailable pills are muted with a
 *      soft strikethrough.
 *   3. A confirmation bar with the exact slot the customer chose,
 *      spelled out in dealer local time (no timezone reshuffle).
 *
 * All labels are pre-formatted by the backend in Asia/Dubai — the frontend
 * never reformats a timestamp. That's what stopped the "customer sees
 * 10:00, operator sees 15:30" mismatch.
 */
export function CalendarPicker({
  conversationId,
  vehicleLabel,
  onBooked,
  onCancel,
}: {
  conversationId: string;
  vehicleLabel: string;
  onBooked: (confirmation: string) => void;
  onCancel?: () => void;
}) {
  const [slots, setSlots] = useState<CalendarSlot[] | null>(null);
  const [selectedDate, setSelectedDate] = useState<string | null>(null);
  const [selectedSlotId, setSelectedSlotId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const response = await api.listSlots();
        if (!cancelled) {
          setSlots(response.slots);
          // Default the calendar to the first day that has any slot.
          const firstDate = response.slots[0]?.iso_date ?? null;
          setSelectedDate(firstDate);
        }
      } catch (exception) {
        if (!cancelled) {
          setError(
            exception instanceof Error
              ? exception.message
              : "Could not load calendar slots.",
          );
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  // Group by date once. Each day carries its own slot list so the UI can
  // pull them by date without re-scanning the full array.
  const days = useMemo(() => {
    if (!slots) return [];
    const byDate = new Map<
      string,
      {
        iso: string;
        day_short: string;
        day_number: string;
        month_short: string;
        slots: CalendarSlot[];
      }
    >();
    for (const slot of slots) {
      const existing = byDate.get(slot.iso_date);
      if (existing) {
        existing.slots.push(slot);
      } else {
        byDate.set(slot.iso_date, {
          iso: slot.iso_date,
          day_short: slot.day_short,
          day_number: slot.day_number,
          month_short: slot.month_short,
          slots: [slot],
        });
      }
    }
    return Array.from(byDate.values());
  }, [slots]);

  const activeDay = days.find((d) => d.iso === selectedDate);
  const daySlots = activeDay?.slots ?? [];
  const selectedSlot = selectedSlotId
    ? slots?.find((s) => s.slot_id === selectedSlotId)
    : null;

  async function confirm() {
    if (!selectedSlotId || busy) return;
    setBusy(true);
    setError(null);
    try {
      const response = await api.bookSlot({
        conversationId,
        slotId: selectedSlotId,
        vehicle: vehicleLabel,
      });
      onBooked(response.confirmation);
    } catch (exception) {
      setError(
        exception instanceof Error
          ? exception.message
          : "Could not book that slot. It may have just been taken — please pick another.",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="animate-rise-in overflow-hidden rounded-panel border border-rule bg-paper shadow-soft">
      <header className="flex items-baseline justify-between gap-4 border-b border-rule bg-offset px-6 py-4">
        <div>
          <p className="text-small font-semibold text-plum">
            Pick a slot for your test drive
          </p>
          <p className="mt-0.5 text-caption text-ink-warm">
            {vehicleLabel} · 2-hour slot · Dubai time
          </p>
        </div>
        {onCancel && (
          <button
            type="button"
            onClick={onCancel}
            className="shrink-0 text-caption text-ink-muted transition-colors hover:text-plum"
          >
            Cancel
          </button>
        )}
      </header>

      {slots === null && !error && (
        <p className="px-6 py-12 text-center text-caption text-ink-faint">
          Loading available slots…
        </p>
      )}

      {slots && slots.length === 0 && !error && (
        <p className="px-6 py-12 text-center text-caption text-ink-muted">
          No slots available in the next two weeks. Please call the showroom.
        </p>
      )}

      {days.length > 0 && (
        <>
          {/* ── Day strip ─────────────────────────────────────── */}
          <div className="border-b border-rule px-6 pb-4 pt-5">
            <p className="label mb-3">Choose a day</p>
            <div className="scroll-warm flex gap-2 overflow-x-auto pb-2">
              {days.map((day) => {
                const isActive = day.iso === selectedDate;
                return (
                  <button
                    key={day.iso}
                    type="button"
                    onClick={() => {
                      setSelectedDate(day.iso);
                      setSelectedSlotId(null);
                    }}
                    className={`flex min-w-[76px] flex-shrink-0 flex-col items-center gap-0.5 rounded-xl border py-3
                      transition-all duration-200 ease-soft
                      ${
                        isActive
                          ? "border-plum bg-plum text-white shadow-soft"
                          : "border-rule bg-paper text-ink hover:-translate-y-0.5 hover:border-brand hover:shadow-soft"
                      }`}
                  >
                    <span
                      className={`text-micro font-bold uppercase ${
                        isActive ? "text-white/60" : "text-ink-faint"
                      }`}
                    >
                      {day.day_short}
                    </span>
                    <span className="tabular text-title font-semibold leading-tight">
                      {day.day_number}
                    </span>
                    <span
                      className={`text-caption ${
                        isActive ? "text-white/60" : "text-ink-muted"
                      }`}
                    >
                      {day.month_short}
                    </span>
                    <span
                      className={`tabular mt-1 text-micro tracking-normal ${
                        isActive ? "text-white/50" : "text-ink-faint"
                      }`}
                    >
                      {day.slots.length} slot{day.slots.length === 1 ? "" : "s"}
                    </span>
                  </button>
                );
              })}
            </div>
          </div>

          {/* ── Time slot pills ─────────────────────────────── */}
          <div className="px-6 py-5">
            <p className="label mb-3">Choose a time · 2 hours each</p>
            <div className="flex flex-wrap gap-2">
              {daySlots.map((slot) => {
                const isSelected = slot.slot_id === selectedSlotId;
                const disabled = !slot.is_available;
                return (
                  <button
                    key={slot.slot_id}
                    type="button"
                    onClick={() => setSelectedSlotId(slot.slot_id)}
                    disabled={disabled || busy}
                    className={`tabular rounded-full border px-4 py-2 font-mono text-caption transition-all duration-200 ease-soft
                      ${
                        isSelected
                          ? "border-brand bg-brand text-white shadow-soft"
                          : disabled
                            ? "border-rule bg-offset text-ink-faint line-through decoration-1"
                            : "border-rule bg-paper text-ink hover:-translate-y-0.5 hover:border-brand hover:shadow-soft"
                      }
                      disabled:cursor-not-allowed disabled:hover:translate-y-0`}
                  >
                    {slot.time_label}
                  </button>
                );
              })}
            </div>

            {daySlots.every((slot) => !slot.is_available) && (
              <p className="mt-4 text-caption text-ink-muted">
                Every slot on this day is taken. Pick another day above.
              </p>
            )}
          </div>
        </>
      )}

      {/* ── Confirm bar ─────────────────────────────────────── */}
      <footer
        className={`border-t px-6 py-4 transition-colors ${
          selectedSlot
            ? "border-brand-edge bg-brand-soft"
            : "border-rule bg-offset"
        }`}
      >
        {error && (
          <p className="mb-3 rounded-xl border border-signal/25 bg-signal/[0.06] px-4 py-2.5 text-caption text-signal">
            {error}
          </p>
        )}
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            {selectedSlot ? (
              <>
                <p className="text-small font-semibold text-plum">
                  {selectedSlot.day_label} · {selectedSlot.time_label}
                </p>
                <p className="mt-0.5 text-caption text-ink-warm">
                  {vehicleLabel} · Dubai time
                </p>
              </>
            ) : (
              <p className="text-caption text-ink-muted">
                Pick a day and a time to confirm.
              </p>
            )}
          </div>
          <button
            type="button"
            onClick={confirm}
            disabled={!selectedSlotId || busy}
            className="btn-primary"
          >
            {busy ? "Booking…" : "Confirm booking"}
          </button>
        </div>
      </footer>
    </section>
  );
}
