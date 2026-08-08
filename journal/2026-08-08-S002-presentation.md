# S002 — Presentation layer

**Date:** 2026-08-08 (Saturday) · **Trajectory:** [T6](../docs/trajectories/T6-presentation.md) ·
**Competency band:** `Create` ·
**Data:** [`data/sessions/2026-08-08-S002.json`](../data/sessions/2026-08-08-S002.json)

## Objectives

| # | Objective | Result |
| --- | --- | --- |
| 1 | Output detects what it is talking to instead of assuming a terminal | ✅ met |
| 2 | Colour never changes what is on the screen, only how it looks | ✅ met — after a failure, see M4 |
| 3 | The score reveal reads as feedback rather than a table | ✅ met |
| 4 | Progression is visible at a glance: world map, star totals, score trend | ✅ met |
| 5 | Every element degrades to ASCII on a non-UTF-8 terminal | ✅ met |
| 6 | S001's recorded friction about hard-coded ANSI codes is resolved | ✅ met |

## What was built

[`vibecoder/ui.py`](../vibecoder/ui.py), a renderer that every piece of output
now goes through, plus 63 tests. `cli.py` no longer contains a single escape
sequence.

**Capability detection comes first.** `detect()` inspects the stream and the
environment and returns a `Capabilities` record: colour depth
(none/16/256/truecolor), Unicode support, whether animation is appropriate, and
the terminal width. `NO_COLOR` wins over everything including `FORCE_COLOR`,
because a user who sets it means it. Animation additionally requires a real TTY,
so a CI run never sleeps in a redraw loop.

**Colour is applied last, always.** Every element computes its plain-text layout
and paints afterwards. That ordering is what makes the central guarantee
possible: escape-stripped output is byte-identical at every colour depth, and
the test suite asserts it for eleven separate elements. It also means tests
compare readable text rather than escape soup.

**Width is a parameter, never a global.** Elements take the width they may use
rather than calling `get_terminal_size` at draw time. Testing a gauge at width 1
and width 60 is then trivial, and nothing silently depends on the 80×24 fallback.

**What got drawn.** Gauges with a red→amber→green gradient tracking their value;
a `gradient_gauge` where each cell is coloured by its own position, which is the
one place truecolor genuinely earns its keep. Sparklines for score history. A
world map with nodes on a six-column pitch and star labels centred beneath. A
block-capital banner tinted across a gradient. Boss health bars — built now,
before [T3](../docs/trajectories/T3-boss-engine.md) needs them, so the boss
fight renders through the same layer rather than growing its own.

The score reveal animates each axis filling in turn. On a pipe the animation
collapses to the final line, so the transcript is identical either way — there
is a test pinning the animated and static paths to the same final frame.

**`showcase` renders everything at once**, including the detected capabilities.
It exists so the layer can be eyeballed without playing a level, and piping it
is the fastest check that nothing leaks.

## Evidence

```
$ python3 -m vibecoder.cli showcase | grep -c $'\033'
0

$ NO_COLOR=1 FORCE_COLOR=3 python3 -m vibecoder.cli showcase | grep -c $'\033'
0

$ python3 -m unittest discover -s tests
Ran 194 tests in 4.214s
OK
```

Visible output across all four colour depths, compared after stripping escapes:

```
none       identical
16         identical
256        identical
truecolor  identical
```

| Claim | Evidence | Verdict |
| --- | --- | --- |
| Piped output contains no escape sequences | `showcase \| grep -c` → 0 | verified |
| `NO_COLOR` overrides `FORCE_COLOR` | `test_no_color_beats_force_color` | verified |
| Colour depth never changes visible output | `TestDepthInvariance`, 11 elements × 4 depths | verified |
| Gauges are exactly their requested width | `TestWidth`, across values 0–500 and widths 1–60 | verified |
| ASCII terminals get no Unicode | `TestGlyphFallback`, asserts `.isascii()` | verified |
| Animation never runs without a TTY | `TestAnimation`, 5 tests | verified |
| Animated and static paths agree on the final frame | `test_reveal_matches_the_static_row` | verified |
| No third-party dependency | Every import across `vibecoder/` is stdlib | verified |
| The layer looks good on a real 24-bit terminal | — | `UNVERIFIED` — rendered and inspected here, but not viewed in a genuine terminal emulator |

## Misconceptions and corrections

### M4 — A background-filled badge is just a nicer-looking badge

**Believed:** rendering `[PASS]` without colour and a background-filled ` PASS `
with it was a clean degradation — same width, better appearance where supported.

**Revealed by:** the depth-invariance check, comparing `showcase` output across
all four depths. Every element matched except one line, and the diff was exactly
the badge row: `[PASS]  [FAIL]` versus ` PASS    FAIL `.

**Corrected to:** brackets at every depth, with the colour applied to the
brackets as well. Visible output is now genuinely identical.

**The interesting part is the temptation.** Criterion 6 says "same layout", and
the filled badge *did* preserve layout — same width, nothing shifted. It would
have taken one word to amend the criterion to "same layout and width" and
declare the trajectory clean. That is precisely the move [N7](../CLAUDE.md)
exists to prevent, and noticing the urge to make it was more instructive than
the bug. The invariant is worth more than the appearance, because "colour never
changes the text" is what lets every other test in the suite compare visible
output and ignore styling entirely.

**Cost:** ~10 minutes. Caught before shipping, by a check written into the
trajectory before the work started.

## Friction

- **`io.StringIO` cannot be used to test capability detection.** Its `encoding`
  is read-only and `isatty()` always returns False, so two tests failed on the
  harness rather than the code. Fixed with a small `FakeStream`; five minutes
  lost to debugging tests instead of the thing under test.
- **`mock.patch.dict` rejects `None` values**, which broke the first attempt at
  "unset these variables". Replaced with `clear=True` and an explicit
  environment, which is clearer anyway.
- **Terminal rendering cannot be fully verified from here.** The layer is
  correct by measurement, but "does it look good" needs a human at a real
  terminal. Recorded honestly as `UNVERIFIED` above.

## Decisions

| # | Decision | Alternatives considered | Rationale | Reversible? |
| --- | --- | --- | --- | --- |
| D7 | Detect capabilities rather than assume a terminal | Always emit colour; a `--color` flag only | Escape codes in a log file are a bug; detection also gives Unicode and animation gating for free | Yes |
| D8 | Colour applied last, layout computed first | Paint inline while building strings | Makes depth-invariance achievable and tests readable | Hard — it is the module's shape |
| D9 | Width as a parameter, not read at draw time | `get_terminal_size()` inside each element | Testability at any width; no hidden dependency on the 80-column fallback | Yes |
| D10 | Brackets on badges at every depth | Background-filled pill when colour is available | Preserves the invariant that colour never changes visible text (M4) | Yes |
| D11 | Build the boss health bar now, before T3 | Wait until the boss engine needs it | The boss fight then renders through the same layer instead of growing a parallel one | Yes |
| D12 | Hand-rolled ANSI rather than `curses` | `curses` is stdlib and would satisfy N1 | `curses` takes over the screen and does not degrade to a pipe; the game prints, it does not own the terminal | Yes |

## Handoff

- **State:** [T6](../docs/trajectories/T6-presentation.md) is `LANDED` — all
  eight exit criteria verified. `vibecoder/ui.py` is the only place escape codes
  are emitted; `cli.py` contains none. 194 tests green, `verify` clean on 18
  reference runs. `showcase` and `levels --map` are new commands. T1 remains
  `LANDED`; nothing in the engine changed.
- **Next action:** unchanged from [S001](2026-08-08-S001-core-loop.md) —
  [T2 W1](../docs/trajectories/T2-sandbox.md), the container-backed runner
  behind `run_code`. T6 was a detour, taken because the friction it resolved was
  cheap to fix now and expensive to fix after a web front-end exists.
- **Blockers:** none for T2 W1–W3. T2 W4 still needs a registered OAuth
  application and the client-versus-server profiling decision.
- **Context required:** [`docs/UI.md`](../docs/UI.md) before adding any visual
  element; M4 above before changing how an element degrades.

## Open questions

| # | Question | Owner trajectory | Status |
| --- | --- | --- | --- |
| Q8 | Should the renderer be injected rather than a module-level `UI` singleton in `cli.py`? It works now, but a web front-end or a test that wants to capture output has to monkey-patch it. | T6 | open |
| Q9 | Animation timing is fixed at ~0.35s per axis. Does that feel right after ten levels, or does it become something to sit through? Needs a real player. | T6 | open |
| Q10 | The banner is drawn from a hand-written ASCII grid. Worth a small figlet-style renderer so world titles can use it too, or is one banner enough? | T6 | open |
