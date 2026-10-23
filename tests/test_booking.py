"""Booking rules. The tests that matter are the refusals.

A booking system that only proves it accepts valid slots is not tested at all --
every bug lives in the boundary cases.
"""
from datetime import date, datetime, time, timedelta

import pytest

from app.booking import (
    DEFAULT_OPENINGS,
    KIND_SPEC,
    MIN_NOTICE,
    Booking,
    Reason,
    SlotKind,
    day_availability,
    evaluate,
    next_available,
)

# A Monday, well in the future, so MIN_NOTICE never interferes by accident.
MON = datetime(2026, 11, 2, 9, 0)
NOW = datetime(2026, 10, 30, 9, 0)


def at(hour, minute=0, day=2):
    return datetime(2026, 11, day, hour, minute)


class TestAccepts:
    def test_simple_discovery_call(self):
        d = evaluate(SlotKind.DISCOVERY, at(10), now=NOW)
        assert d.allowed and d.reason is Reason.OK

    def test_workshop_needs_two_hours(self):
        d = evaluate(SlotKind.WORKSHOP, at(9), now=NOW)
        assert d.allowed, d.detail
        assert d.end - d.start == timedelta(minutes=120)

    def test_morning_slot_before_lunch(self):
        # 11:00 + 60 min ends 12:00, clear of the 12:30 break.
        assert evaluate(SlotKind.REVIEW, at(11), now=NOW).allowed


class TestHours:
    def test_weekend_is_closed(self):
        d = evaluate(SlotKind.DISCOVERY, datetime(2026, 11, 7, 10, 0), now=NOW)  # Saturday
        assert not d.allowed and d.reason is Reason.CLOSED

    def test_friday_afternoon_is_closed(self):
        # Friday closes at 13:00.
        d = evaluate(SlotKind.DISCOVERY, datetime(2026, 11, 6, 14, 0), now=NOW)
        assert not d.allowed and d.reason is Reason.OUTSIDE_HOURS

    def test_slot_cannot_run_past_closing(self):
        # 17:30 + 60 min runs to 18:30, past the 18:00 close.
        d = evaluate(SlotKind.REVIEW, at(17, 30), now=NOW)
        assert not d.allowed and d.reason is Reason.OUTSIDE_HOURS

    def test_before_opening(self):
        d = evaluate(SlotKind.DISCOVERY, at(8), now=NOW)
        assert not d.allowed and d.reason is Reason.OUTSIDE_HOURS

    def test_lunch_is_protected(self):
        # 12:00 + 60 crosses into the 12:30-13:30 break.
        d = evaluate(SlotKind.REVIEW, at(12), now=NOW)
        assert not d.allowed
        assert "12:30" in d.detail


class TestNotice:
    def test_past_slot_is_refused(self):
        d = evaluate(SlotKind.DISCOVERY, at(10), now=at(11))
        assert not d.allowed and d.reason is Reason.PAST

    def test_inside_min_notice_is_refused(self):
        now = at(9) - timedelta(hours=2)
        d = evaluate(SlotKind.DISCOVERY, at(9), now=now)
        assert not d.allowed and d.reason is Reason.TOO_SHORT_NOTICE

    def test_exactly_at_notice_is_allowed(self):
        start = at(9)
        d = evaluate(SlotKind.DISCOVERY, start, now=start - MIN_NOTICE)
        assert d.allowed


class TestConflicts:
    def test_overlap_is_refused(self):
        existing = [Booking(SlotKind.DISCOVERY, at(10), 30, "ACME")]
        d = evaluate(SlotKind.DISCOVERY, at(10, 15), existing, now=NOW)
        assert not d.allowed and d.reason is Reason.OVERLAP
        assert "ACME" in d.detail

    def test_touching_edges_do_not_overlap(self):
        # One ends at 10:30, the next starts at 10:30. That is not an *overlap*,
        # but it does consume the 15-minute prep buffer, so the booking is still
        # refused -- for the buffer reason, not the clash reason.
        existing = [Booking(SlotKind.DISCOVERY, at(10), 30)]
        d = evaluate(SlotKind.DISCOVERY, at(10, 30), existing, now=NOW)
        assert d.reason is not Reason.OVERLAP, "touching edges must not count as a clash"
        assert d.reason is Reason.NO_BUFFER

    def test_touching_edges_allowed_when_kind_needs_no_buffer(self):
        existing = [Booking(SlotKind.DISCOVERY, at(10), 30)]
        d = evaluate(SlotKind.DISCOVERY, at(10, 45), existing, now=NOW)
        assert d.allowed, d.detail

    def test_prep_buffer_is_kept(self):
        # A discovery call ends 10:30; a workshop needs 30 min of prep, so the
        # earliest a workshop may start is 11:00. (11:00 itself would run into
        # the lunch break, so 13:30 is the first slot that satisfies both.)
        existing = [Booking(SlotKind.DISCOVERY, at(10), 30)]
        blocked = evaluate(SlotKind.WORKSHOP, at(10, 30), existing, now=NOW)
        allowed = evaluate(SlotKind.WORKSHOP, at(13, 30), existing, now=NOW)
        assert not blocked.allowed and blocked.reason is Reason.NO_BUFFER
        assert allowed.allowed, allowed.detail

    def test_buffer_reported_for_ui(self):
        d = evaluate(SlotKind.WORKSHOP, at(9), now=NOW)
        assert d.buffer_from == at(9) - timedelta(minutes=30)


class TestAvailabilityGrid:
    def test_grid_only_offers_open_days(self):
        sat = date(2026, 11, 7)
        assert day_availability(sat, SlotKind.DISCOVERY, now=NOW) == []

    def test_grid_matches_working_window(self):
        mon = date(2026, 11, 2)
        grid = day_availability(mon, SlotKind.DISCOVERY, now=NOW, step_min=60)
        # 09:00-18:00 by the hour = 9 candidates (18:00 closes, not a start).
        assert len(grid) == 9
        assert grid[0].start == datetime(2026, 11, 2, 9, 0)

    def test_grid_marks_refusals_with_reasons(self):
        mon = date(2026, 11, 2)
        grid = day_availability(mon, SlotKind.REVIEW, now=NOW, step_min=30)
        reasons = {d.reason for d in grid if not d.allowed}
        # 17:30 + 60 runs past the 18:00 close.
        assert Reason.OUTSIDE_HOURS in reasons
        assert any(d.allowed for d in grid), "a normal Monday must offer something"

    def test_next_available_skips_the_weekend(self):
        fri_afternoon = datetime(2026, 11, 6, 15, 0)
        d = next_available(SlotKind.DISCOVERY, fri_afternoon)
        assert d is not None
        assert d.start.weekday() == 0, "should roll to Monday, not Saturday"

    def test_next_available_respects_existing(self):
        start = datetime(2026, 11, 2, 9, 0)
        existing = [Booking(SlotKind.DISCOVERY, start, 30)]
        d = next_available(SlotKind.DISCOVERY, start - MIN_NOTICE, existing)
        assert d is not None and d.start > start

    def test_no_availability_returns_none(self):
        # A practice with no openings can never book.
        assert next_available(SlotKind.DISCOVERY, datetime(2026, 11, 2, 9),
                              openings=()) is None


class TestKindSpec:
    def test_every_kind_has_a_duration_and_buffer(self):
        for kind in SlotKind:
            duration, buffer_min = KIND_SPEC[kind]
            assert duration > 0 and buffer_min >= 0

    def test_every_opening_is_a_valid_window(self):
        for o in DEFAULT_OPENINGS:
            assert o.start < o.end
            assert 0 <= o.weekday <= 6
