"""Keystroke rhythm: the signal the profiler cannot currently see. T7 W6.

The Vibe Profiler reads finished source and infers habits from the residue.
It never sees the part that is arguably most characteristic of how somebody
writes code -- the bursts, the pauses before a hard line, the long silence
that means they are reading rather than typing. Sitting inside the editor
makes that observable.

Every method takes an explicit ``now``. That is not decoration: it is what
lets the whole module be tested without sleeping, which is the difference
between a fast suite and a flaky one.

**This is behavioural data about a person.** It stays on the machine that
produced it, exactly like source under T2's ingestion commitment, and it is
not attached to a score submission. See the hazard list in
[T7](../docs/trajectories/T7-interactive.md).
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field

#: Seconds of history the rhythm display covers.
WINDOW = 8.0
#: Keystroke energy halves this often, which is what makes the glow decay.
HALF_LIFE = 0.45
#: Faster than this between keys and it counts as a burst.
BURST_INTERVAL = 0.14
#: Silence longer than this reads as thinking rather than as idling.
THINKING_AFTER = 1.2
IDLE_AFTER = 8.0
#: A "word" for words-per-minute purposes. The standard typing-test unit.
CHARS_PER_WORD = 5


@dataclass
class Pulse:
    """A decaying record of recent keystrokes."""

    window: float = WINDOW
    _times: deque[float] = field(default_factory=lambda: deque(maxlen=512))
    _last: float = 0.0
    _total: int = 0

    # -- recording ---------------------------------------------------------

    def press(self, at: float | None = None) -> None:
        now = time.monotonic() if at is None else at
        self._times.append(now)
        self._last = now
        self._total += 1

    def _prune(self, now: float) -> None:
        cutoff = now - self.window
        while self._times and self._times[0] < cutoff:
            self._times.popleft()

    # -- reading -----------------------------------------------------------

    @property
    def total(self) -> int:
        return self._total

    def energy(self, now: float | None = None) -> float:
        """0..1, decaying from the last keystroke. Drives the glow."""
        now = time.monotonic() if now is None else now
        if not self._last:
            return 0.0
        elapsed = max(0.0, now - self._last)
        return 0.5 ** (elapsed / HALF_LIFE)

    def wpm(self, now: float | None = None) -> float:
        """Words per minute over the window, from characters typed."""
        now = time.monotonic() if now is None else now
        self._prune(now)
        if len(self._times) < 2:
            return 0.0
        span = self._times[-1] - self._times[0]
        if span <= 0:
            return 0.0
        # n keystrokes bracket n-1 intervals. Counting n over the span between
        # the first and last inflates the rate -- by 5% at twenty keys, more
        # at fewer, which is exactly when the number is most visible.
        characters = len(self._times) - 1
        return (characters / CHARS_PER_WORD) / (span / 60.0)

    def intervals(self, now: float | None = None) -> list[float]:
        now = time.monotonic() if now is None else now
        self._prune(now)
        times = list(self._times)
        return [b - a for a, b in zip(times, times[1:])]

    def evenness(self, now: float | None = None) -> float:
        """0..1. High means a steady cadence, low means stop-start.

        Reported rather than scored: N5 says an axis that cannot be measured
        honestly must not be scored, and what an even cadence *means* about
        a programmer is not established. It is an observation for now.
        """
        gaps = self.intervals(now)
        if len(gaps) < 3:
            return 0.0
        mean = sum(gaps) / len(gaps)
        if mean <= 0:
            return 0.0
        variance = sum((g - mean) ** 2 for g in gaps) / len(gaps)
        # Coefficient of variation, inverted and clamped.
        spread = (variance ** 0.5) / mean
        return max(0.0, min(1.0, 1.0 - spread))

    def state(self, now: float | None = None) -> str:
        """``burst`` / ``typing`` / ``thinking`` / ``idle``."""
        now = time.monotonic() if now is None else now
        if not self._last:
            return "idle"
        quiet = now - self._last
        if quiet > IDLE_AFTER:
            return "idle"
        if quiet > THINKING_AFTER:
            return "thinking"
        gaps = self.intervals(now)
        recent = gaps[-4:]
        if recent and sum(recent) / len(recent) < BURST_INTERVAL:
            return "burst"
        return "typing"

    def trail(self, width: int = 24, now: float | None = None) -> list[float]:
        """Keystroke density per time bucket, oldest first, each 0..1.

        This is the moving part of the visualiser: the window scrolls with
        real time, so the trail drifts left and fades even when nothing is
        being typed. A still display would not show a pause, and the pause is
        the interesting part.
        """
        now = time.monotonic() if now is None else now
        self._prune(now)
        if width <= 0:
            return []
        buckets = [0.0] * width
        span = self.window / width
        for stamp in self._times:
            age = now - stamp
            index = width - 1 - int(age / span)
            if 0 <= index < width:
                buckets[index] += 1.0
        peak = max(buckets)
        if peak <= 0:
            return buckets
        return [value / peak for value in buckets]

    def reset(self) -> None:
        self._times.clear()
        self._last = 0.0
        self._total = 0
