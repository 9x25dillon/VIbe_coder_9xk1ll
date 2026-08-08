# T6 — Presentation layer

**Design phase:** cross-cutting · **Status:** `LANDED` 2026-08-08 ·
**Depends on:** T1 (`LANDED`) ·
**Evidence:** [journal/2026-08-08-S002-presentation.md](../../journal/2026-08-08-S002-presentation.md)

## Heading

The scoring system says something interesting and currently says it in plain
text with hard-coded escape codes. That is a problem twice over.

First, **the product is a game**. A score reveal that animates, a level map you
can see your progress across, a gauge that turns from red to green as it fills —
these are not decoration, they are how the three axes stop being a table of
numbers and start being feedback. The design document's whole pitch rests on the
player *feeling* the difference between a correct-but-slow solution and a good
one.

Second, [S001 recorded ANSI codes hard-coded in `cli.py` as
friction](../../journal/2026-08-08-S001-core-loop.md#friction): "adequate for a
prototype, wrong for anything embedded". Every consumer that is not an
interactive terminal — a pipe, a CI log, a file, the web front-end that arrives
eventually — currently gets escape sequences it did not ask for. Fixing that
properly means a presentation layer that *detects what it is talking to* rather
than assuming.

Doing both at once is the right call: the capability detection that makes output
safe in a pipe is the same machinery that lets a truecolor terminal get a smooth
gradient.

## Waypoints

| ID | Waypoint | State |
| --- | --- | --- |
| W1 | Capability detection: truecolor / 256 / 16 / none, plus Unicode support | done |
| W2 | Palette with automatic downgrade across colour depths | done |
| W3 | Static primitives: gauges, sparklines, stars, rules, boxes, badges | done |
| W4 | Animation helpers that no-op when not a TTY | done |
| W5 | Animated score reveal wired into `play` | done |
| W6 | Level map showing world progression and stars | done |
| W7 | Vibe Vector chart in `profile` | done |
| W8 | Boss health bar primitive, ready for T3 | done |
| W9 | `showcase` command rendering every element | done |

## Exit criteria

Written before implementation; all verified the same day.

| # | Criterion | Result |
| --- | --- | --- |
| 1 | Piping any command to a file produces **zero** escape sequences | ✅ `showcase \| grep -c $'\033'` → 0 |
| 2 | `NO_COLOR=1` produces zero escape sequences even on a TTY | ✅ 0, and it beats `FORCE_COLOR=3` (`test_no_color_beats_force_color`) |
| 3 | A terminal without Unicode support gets ASCII fallbacks, not mojibake | ✅ `TestGlyphFallback`, asserts `.isascii()` across elements |
| 4 | Every rendered element respects the terminal width and never wraps | ✅ `TestWidth`, 6 tests; gauges are exactly their width at any value |
| 5 | Animation is skippable and never blocks a non-interactive run | ✅ `TestAnimation`, 5 tests; animated and static paths produce the same final frame |
| 6 | Colour depth degrades cleanly: truecolor → 256 → 16 → none, same layout | ✅ `TestDepthInvariance`, 11 elements byte-identical after stripping escapes |
| 7 | No third-party dependency (N1 holds) | ✅ every import across `vibecoder/` is stdlib |
| 8 | Existing CLI output keeps its information content — visuals add, never replace | ✅ every field present before is still present |

## What actually went wrong

**Criterion 6 failed on the first measurement.** `badge()` rendered `[PASS]`
without colour and a background-filled ` PASS ` with it — the same *width*, so
the layout was unaffected, but different visible text. The escape-stripped
output therefore differed between depths.

The tempting fix was to soften criterion 6 to "same layout and width", which it
technically already met. That is exactly the move N7 exists to prevent, so the
code changed instead: badges are bracketed at every depth and colour is applied
to the brackets too. The filled pill looked better; the invariant is worth more,
because it is what lets the entire test suite compare visible output and ignore
colour.

## Known hazards

- **Escape codes in test assertions.** Tests must compare against *plain* output
  or they become unreadable and brittle. The renderer needs a hard "no colour"
  mode that tests use exclusively.
- **Width assumptions.** `shutil.get_terminal_size` returns 80×24 when it cannot
  detect. Every element must take width as a parameter rather than reading the
  terminal at draw time, so it stays testable.
- **Animation in CI.** A sleep loop in a non-interactive run wastes time and
  produces garbage. Gate on `isatty` and honour an env override.
- **Unicode is not universal.** Box-drawing and block characters fail on a
  terminal set to a non-UTF-8 encoding. Detect via `stream.encoding` and fall
  back to ASCII.
- **Scope.** A terminal UI can absorb unlimited effort. This trajectory covers
  the presentation of things that already exist; it does not introduce new game
  mechanics.

## Instrument checks

- Render every primitive at colour depths `none`/`16`/`256`/`truecolor` and
  assert the visible (escape-stripped) output is identical across all four.
- Assert every element's rendered width is within its budget for a range of
  terminal widths.
- `python3 -m vibecoder.cli showcase | cat` must contain no `\033`.
