"""
Moving an appointment to a time that overlaps its own current slot.

On 16 Nov a caller with a 9:00-10:00 Square appointment asked to move it to 9:30.
Availability counts every booking as busy, including the one being moved, so
9:30 was never offered and the assistant said it wasn't available.

The appointment's own slot shouldn't block it, but we can't simply ignore it:
we would also need to know the team member's working hours and other bookings,
which Square doesn't expose directly. So we use only what Square has just
told us. Each start time Square offers for that team member and service proves
that its whole window [a, a+length) is free and within working hours. The
appointment's own slot [S, S+length) is busy only because of the appointment
itself. A target window [t, t+length) is therefore free once the appointment
moves if it is completely covered by the union of those windows.

That can only miss a good time, for example one starting before the first
offered window of the day. It can never offer a time that isn't free.
Everything here is pure; the callers do the Square reads.
"""
from __future__ import annotations

from datetime import datetime, timedelta


def overlaps(start: datetime, minutes: int, other_start: datetime, other_minutes: int) -> bool:
    return start < other_start + timedelta(minutes=other_minutes) and \
        other_start < start + timedelta(minutes=minutes)


def covered(target: datetime, minutes: int, own_start: datetime, own_minutes: int,
            free_starts: list[datetime], free_minutes: int) -> bool:
    """Is [target, target+minutes) inside own slot ∪ the free windows?"""
    end = target + timedelta(minutes=minutes)
    spans = [(own_start, own_start + timedelta(minutes=own_minutes))]
    spans += [(a, a + timedelta(minutes=free_minutes)) for a in free_starts]
    spans.sort()
    reach = target
    for s, e in spans:
        if s > reach:
            if s >= end:
                break
            continue
        if e > reach:
            reach = e
        if reach >= end:
            return True
    return reach >= end


def step_minutes(free_starts: list[datetime], default: int = 30) -> int:
    """The spacing Square uses between offered starts (smallest gap, 5-60 min)."""
    gaps = sorted({int((b - a).total_seconds() // 60)
                   for a, b in zip(sorted(free_starts), sorted(free_starts)[1:])
                   if b > a})
    for g in gaps:
        if 5 <= g <= 60:
            return g
    return default


def extra_starts(*, own_start: datetime, minutes: int, free_starts: list[datetime],
                 not_before: datetime) -> list[datetime]:
    """Start times that overlap the appointment's own slot and are free once it moves.

    Candidates are spaced like Square's own offers, aligned to the current start,
    and never the current start itself (that is not a move)."""
    step = step_minutes(free_starts)
    out = []
    k_max = max(1, minutes // step)
    for k in range(-k_max, k_max + 1):
        if k == 0:
            continue
        t = own_start + timedelta(minutes=k * step)
        if t <= not_before or t.date() != own_start.date():
            continue
        if not overlaps(t, minutes, own_start, minutes):
            continue
        if t in free_starts:
            continue
        if covered(t, minutes, own_start, minutes, free_starts, minutes):
            out.append(t)
    return out
