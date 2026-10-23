"""Booking rules for a consulting practice.

The interesting part of a booking system is not the calendar -- it is the
constraints. A two-hour workshop cannot start at 16:00 if the room closes at
18:00. A client cannot book a slot that overlaps one they already hold. A
discovery call needs a buffer before it so the consultant can read the brief.

This module is pure: given openings and existing bookings, decide what a request
may and may not have, and say why. No database, no framework, no clock other than
the one passed in.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from enum import Enum


class SlotKind(str, Enum):
    DISCOVERY = "discovery"
    WORKSHOP = "workshop"
    REVIEW = "review"
    RETAINER = "retainer"


# Duration in minutes and the buffer required *before* the slot.
KIND_SPEC: dict[SlotKind, tuple[int, int]] = {
    SlotKind.DISCOVERY: (30, 15),
    SlotKind.WORKSHOP: (120, 30),
    SlotKind.REVIEW: (60, 30),
    SlotKind.RETAINER: (90, 30),
}

KIND_LABEL = {
    SlotKind.DISCOVERY: "Discovery call",
    SlotKind.WORKSHOP: "Workshop",
    SlotKind.REVIEW: "Architecture review",
    SlotKind.RETAINER: "Retainer session",
}


class Reason(str, Enum):
    OK = "ok"
    CLOSED = "closed"                     # practice does not work that day
    OUTSIDE_HOURS = "outside_hours"       # slot falls outside opening hours
    TOO_SHORT_NOTICE = "too_short_notice"
    OVERLAP = "overlap"                   # clashes with an existing booking
    NO_BUFFER = "no_buffer"               # would not leave the prep buffer
    PAST = "past"


@dataclass(frozen=True)
class Opening:
    """A working window, in local time."""

    weekday: int          # 0 = Monday
    start: time
    end: time

    def covers(self, start: datetime, end_dt: datetime) -> bool:
        if start.weekday() != self.weekday:
            return False
        return start.time() >= self.start and end_dt.time() <= self.end


@dataclass(frozen=True)
class Booking:
    kind: SlotKind
    start: datetime
    duration_min: int
    reference: str = ""

    @property
    def end(self) -> datetime:
        return self.start + timedelta(minutes=self.duration_min)

    def overlaps(self, other_start: datetime, other_end: datetime) -> bool:
        # Touching edges (one ends exactly when the next starts) is not an overlap.
        return self.start < other_end and other_start < self.end


@dataclass
class Decision:
    allowed: bool
    reason: Reason
    detail: str = ""
    start: datetime | None = None
    end: datetime | None = None
    buffer_from: datetime | None = None

    def as_dict(self) -> dict:
        return {
            "allowed": self.allowed,
            "reason": self.reason.value,
            "detail": self.detail,
            "start": self.start.isoformat() if self.start else None,
            "end": self.end.isoformat() if self.end else None,
        }


# The practice does not work Friday afternoons, and takes a minimum of one
# working day of notice so the brief can be read.
DEFAULT_OPENINGS: tuple[Opening, ...] = (
    Opening(0, time(9, 0), time(18, 0)),
    Opening(1, time(9, 0), time(18, 0)),
    Opening(2, time(9, 0), time(18, 0)),
    Opening(3, time(9, 0), time(18, 0)),
    Opening(4, time(9, 0), time(13, 0)),
)

MIN_NOTICE = timedelta(hours=24)
LUNCH = (time(12, 30), time(13, 30))


def _in_lunch(start: datetime, end_dt: datetime) -> bool:
    """A slot may not straddle the lunch break."""
    return start.time() < LUNCH[1] and end_dt.time() > LUNCH[0]


def evaluate(
    kind: SlotKind,
    start: datetime,
    existing: list[Booking] | None = None,
    now: datetime | None = None,
    openings: tuple[Opening, ...] = DEFAULT_OPENINGS,
) -> Decision:
    """
    Decide whether a requested slot is bookable, and say why not.

    Checks run cheapest-first and the first failure wins, so the caller gets the
    most actionable reason rather than a list.
    """
    existing = existing or []
    duration, buffer_min = KIND_SPEC[kind]
    end_dt = start + timedelta(minutes=duration)

    if now is not None:
        if start < now:
            return Decision(False, Reason.PAST, "That time has already passed.")
        if start - now < MIN_NOTICE:
            return Decision(
                False,
                Reason.TOO_SHORT_NOTICE,
                f"Bookings need at least {int(MIN_NOTICE.total_seconds() // 3600)} hours of notice.",
                start,
                end_dt,
            )

    if not any(o.covers(start, end_dt) for o in openings):
        weekday_open = any(o.weekday == start.weekday() for o in openings)
        if not weekday_open:
            return Decision(False, Reason.CLOSED, "The practice is closed that day.", start, end_dt)
        return Decision(
            False,
            Reason.OUTSIDE_HOURS,
            "That slot falls outside working hours.",
            start,
            end_dt,
        )

    if _in_lunch(start, end_dt):
        return Decision(
            False,
            Reason.OUTSIDE_HOURS,
            "That slot runs through the 12:30-13:30 break.",
            start,
            end_dt,
        )

    buffer_from = start - timedelta(minutes=buffer_min)
    for b in existing:
        if b.overlaps(start, end_dt):
            return Decision(
                False,
                Reason.OVERLAP,
                f"That clashes with {KIND_LABEL[b.kind].lower()}"
                + (f" ({b.reference})" if b.reference else "")
                + ".",
                start,
                end_dt,
            )
        # The buffer only has to be clear of *other* bookings, not of the slot.
        if buffer_min and b.start < start and b.end > buffer_from:
            return Decision(
                False,
                Reason.NO_BUFFER,
                f"Only {buffer_min} minutes of prep time is kept before this slot.",
                start,
                end_dt,
            )

    return Decision(True, Reason.OK, "", start, end_dt, buffer_from)


def day_availability(
    on: date,
    kind: SlotKind,
    existing: list[Booking] | None = None,
    now: datetime | None = None,
    openings: tuple[Opening, ...] = DEFAULT_OPENINGS,
    step_min: int = 30,
) -> list[Decision]:
    """
    Every candidate start time for a given day, with its verdict.

    Used by the UI to render a real grid rather than a list of hard-coded times.
    """
    out: list[Decision] = []
    for o in openings:
        if o.weekday != on.weekday():
            continue
        cursor = datetime.combine(on, o.start)
        limit = datetime.combine(on, o.end)
        while cursor < limit:
            out.append(evaluate(kind, cursor, existing, now, openings))
            cursor += timedelta(minutes=step_min)
    return out


def next_available(
    kind: SlotKind,
    after: datetime,
    existing: list[Booking] | None = None,
    days: int = 21,
    openings: tuple[Opening, ...] = DEFAULT_OPENINGS,
    step_min: int = 30,
) -> Decision | None:
    """The soonest bookable slot, or None inside the search window."""
    for i in range(days):
        day = (after + timedelta(days=i)).date()
        for d in day_availability(day, kind, existing, after, openings, step_min):
            if d.allowed:
                return d
    return None
