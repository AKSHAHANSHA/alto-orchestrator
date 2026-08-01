"""Test-drive slot generation and booking.

Slots are generated deterministically from the showroom's opening hours —
same rules the customer chat page reads from
`01-showroom-hours-and-visits.md` and `02-test-drive-procedure.md`.
Availability is real: a slot booked by one customer is not offered to
another.

Slot semantics:
- Each slot is **exactly two hours**.
- Slots start on the hour and fit inside that day's opening window.
- Past slots are hidden.
- Booked slots are hidden.

Bookings are held in-process for now (same durability class as the rest of
conversation state). Persistence lives on the H-2 backlog.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from app.core.logging import get_logger

logger = get_logger(__name__)

# Local time throughout. Alto Motors is in Dubai (UTC+4, no DST), so wall
# time and stored time are the same string. The backend formats everything
# it wants displayed and the frontend never reformats it — that's the fix
# for "the customer sees 10:00 and the operator sees 15:30" bug.
DEALER_TZ = ZoneInfo("Asia/Dubai")

# Weekday index (Monday=0) → test-drive window (open, close) in local wall time.
# Windows are tightened slightly from raw showroom hours so drives don't run
# past closing.
_TEST_DRIVE_WINDOWS: dict[int, tuple[time, time]] = {
    0: (time(9, 0), time(19, 0)),   # Monday
    1: (time(9, 0), time(19, 0)),   # Tuesday
    2: (time(9, 0), time(19, 0)),   # Wednesday
    3: (time(9, 0), time(19, 0)),   # Thursday
    4: (time(14, 0), time(20, 0)),  # Friday — congregational-prayer close in the morning
    5: (time(10, 0), time(20, 0)),  # Saturday
    6: (time(10, 0), time(18, 0)),  # Sunday
}

# Slot length. Two hours per the updated policy.
SLOT_HOURS = 2

# How many days out from today to expose in the calendar.
DEFAULT_HORIZON_DAYS = 14


@dataclass(frozen=True)
class SlotOption:
    """One 2-hour slot the customer may pick.

    Every string field is pre-formatted in dealer local time. The frontend
    renders these verbatim rather than reformatting from ``start`` — that's
    what stops the timezone mismatch between chat and operator views.
    """

    slot_id: str
    start: datetime
    end: datetime
    is_available: bool
    day_short: str        # "Sun"
    day_number: str       # "03"
    month_short: str      # "Aug"
    day_label: str        # "Sun 03 Aug"
    time_label: str       # "09:00–11:00"
    iso_date: str         # "2026-08-03" — for grouping

    def to_dict(self) -> dict[str, Any]:
        return {
            "slot_id": self.slot_id,
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "is_available": self.is_available,
            "day_short": self.day_short,
            "day_number": self.day_number,
            "month_short": self.month_short,
            "day_label": self.day_label,
            "time_label": self.time_label,
            "iso_date": self.iso_date,
        }


@dataclass
class Booking:
    id: str
    conversation_id: str
    slot_id: str
    slot_start: datetime
    slot_end: datetime
    customer_name: str | None
    vehicle: str
    contact_phone: str | None
    created_at: datetime = field(default_factory=lambda: datetime.now(DEALER_TZ))
    status: str = "confirmed"
    notified_operator: bool = False

    @property
    def day_label(self) -> str:
        return self.slot_start.strftime("%a %d %b")

    @property
    def time_label(self) -> str:
        return f"{self.slot_start.strftime('%H:%M')}–{self.slot_end.strftime('%H:%M')}"

    @property
    def slot_label(self) -> str:
        """The one string everyone should show for this booking.

        Backend-owned formatting so the customer's chat, the confirmation
        message, and the operator dashboard all display the same wall time
        for the same slot.
        """
        return f"{self.day_label} · {self.time_label}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "conversation_id": self.conversation_id,
            "slot_id": self.slot_id,
            "slot_start": self.slot_start.isoformat(),
            "slot_end": self.slot_end.isoformat(),
            "day_label": self.day_label,
            "time_label": self.time_label,
            "slot_label": self.slot_label,
            "customer_name": self.customer_name,
            "vehicle": self.vehicle,
            "contact_phone": self.contact_phone,
            "created_at": self.created_at.isoformat(),
            "status": self.status,
        }


class AppointmentService:
    """Generates test-drive slots and holds bookings.

    Kept intentionally simple: an in-memory dict keyed by slot id. Two
    customers picking the same slot at the same instant is guarded by
    lookup-then-write in `book_slot`.
    """

    def __init__(self) -> None:
        self._bookings: dict[str, Booking] = {}
        self._slot_to_booking: dict[str, str] = {}

    # ── Slot generation ──────────────────────────────────────────────
    def available_slots(
        self, from_date: datetime | None = None, horizon_days: int = DEFAULT_HORIZON_DAYS
    ) -> list[SlotOption]:
        """Every slot from now to `horizon_days` days out, in dealer local time.

        Past slots and booked slots are filtered here so the client cannot
        pick something invalid. Every rendered string (day, time, label) is
        formatted once, here, so no downstream code has to guess a timezone.
        """
        now = from_date or datetime.now(DEALER_TZ)
        slots: list[SlotOption] = []

        for day_offset in range(horizon_days):
            day = now + timedelta(days=day_offset)
            weekday = day.weekday()
            window = _TEST_DRIVE_WINDOWS.get(weekday)
            if window is None:
                continue

            open_time, close_time = window
            start_dt = day.replace(
                hour=open_time.hour, minute=open_time.minute, second=0, microsecond=0
            )
            close_dt = day.replace(
                hour=close_time.hour, minute=close_time.minute, second=0, microsecond=0
            )

            while start_dt + timedelta(hours=SLOT_HOURS) <= close_dt:
                end_dt = start_dt + timedelta(hours=SLOT_HOURS)
                slot_id = f"slot_{start_dt.strftime('%Y%m%dT%H%M')}"

                if start_dt < now:
                    start_dt = end_dt
                    continue

                is_available = slot_id not in self._slot_to_booking

                slots.append(
                    SlotOption(
                        slot_id=slot_id,
                        start=start_dt,
                        end=end_dt,
                        is_available=is_available,
                        day_short=start_dt.strftime("%a"),
                        day_number=start_dt.strftime("%d"),
                        month_short=start_dt.strftime("%b"),
                        day_label=start_dt.strftime("%a %d %b"),
                        time_label=(
                            f"{start_dt.strftime('%H:%M')}–{end_dt.strftime('%H:%M')}"
                        ),
                        iso_date=start_dt.strftime("%Y-%m-%d"),
                    )
                )
                start_dt = end_dt

        return slots

    # ── Booking ───────────────────────────────────────────────────────
    def book_slot(
        self,
        *,
        conversation_id: str,
        slot_id: str,
        vehicle: str,
        customer_name: str | None = None,
        contact_phone: str | None = None,
    ) -> Booking:
        """Take a slot for a customer.

        Raises `SlotUnavailable` if the slot has already been taken (or
        doesn't parse). The frontend should refresh its slot list on that
        exception and let the customer pick again.
        """
        if slot_id in self._slot_to_booking:
            raise SlotUnavailable(
                f"Slot {slot_id} has just been booked by someone else."
            )

        # Parse the slot's start time from the id — the id encodes it, so we
        # do not need to hold every generated slot in memory to book against
        # it. Format: slot_YYYYMMDDTHHMM, always dealer local time.
        try:
            start = datetime.strptime(
                slot_id.removeprefix("slot_"), "%Y%m%dT%H%M"
            ).replace(tzinfo=DEALER_TZ)
        except ValueError as exc:
            raise SlotUnavailable(f"Unrecognised slot id: {slot_id}") from exc

        end = start + timedelta(hours=SLOT_HOURS)
        booking = Booking(
            id=f"bk_{uuid.uuid4().hex[:12]}",
            conversation_id=conversation_id,
            slot_id=slot_id,
            slot_start=start,
            slot_end=end,
            customer_name=customer_name,
            vehicle=vehicle,
            contact_phone=contact_phone,
        )

        self._bookings[booking.id] = booking
        self._slot_to_booking[slot_id] = booking.id
        logger.info(
            "test_drive_booked",
            booking_id=booking.id,
            slot=slot_id,
            vehicle=vehicle,
            conversation_id=conversation_id,
        )
        return booking

    def mark_notified(self, booking_id: str) -> None:
        booking = self._bookings.get(booking_id)
        if booking:
            booking.notified_operator = True

    def list_recent(self, limit: int = 20) -> list[Booking]:
        return sorted(
            self._bookings.values(), key=lambda b: b.created_at, reverse=True
        )[:limit]

    def get(self, booking_id: str) -> Booking | None:
        return self._bookings.get(booking_id)


class SlotUnavailable(RuntimeError):
    """Raised when a booking attempt finds the slot already taken."""
