# The machine view

```bash
vibecoder vision                 # animate your most recent run
vibecoder vision <run-id> --step # one frame per keypress
vibecoder vision --function tally
```

A score tells a player *that* their solution cost 5,958 operations. It does not
show them why, and why is the thing the Functional axis exists to teach. The
machine view draws the submitted function as apparatus — statements are boxes
wired top to bottom, a loop is a box with a return rail down its left side — and
then walks the recorded execution through it.

```
╭─ total_revenue(sales, threshold) ───────────────────────────╮
  ┌────────────────────────────────────┐
  │ total = 0.0                        │
  └────────────────────────────────────┘
╭ ┌────────────────────────────────────┐
│ │ for sale in sales                  │ ↻ 5
│ └────────────────────────────────────┘
│    ┌─────────────────────────────────┐
│    │ if sale['price'] >= threshold   │
│    └─────────────────────────────────┘
│       ┌──────────────────────────────┐
● │     │ total += sale['price'] * ... │ total = 137.5
╰─      └──────────────────────────────┘
  ┌────────────────────────────────────┐
  │ return round(total, 2)             │
  └────────────────────────────────────┘
╰─────────────────────────────────────────────────────────────╯
  step 11/14   sales = [{'product': 'widget', ...}]   total = 137.5
```

The token `●` is where control is. The counter `↻ 5` climbs every time control
comes back round a loop. An O(n²) solution is visibly a machine whose inner ring
spins while the outer one barely turns — which is the same fact the Functional
score reports as a number.

## Two properties that make it honest

**It is driven by the recording, never by the source.** Frames come from the
same line-by-line trace [`replay.py`](../vibecoder/replay.py) consumes and
[T3](trajectories/T3-boss-engine.md)'s live engine will consume. Nothing here
re-executes anything and nothing guesses: if the trace says control was on line
7, the box holding line 7 lights up. **A branch that was never taken never
lights up**, which is a thing worth being able to see.

**Every frame is a value.** `render` returns a `Screen`, so a test asserts on
`as_text()` with no terminal involved and no pty, exactly as the editor is
tested. The escape-stripped output is identical at every colour depth (the T6
rule), and `vision.py` writes no escape sequence of its own — styles arrive
through `ui.Renderer.style` and the escapes are `Screen.diff`'s business.

## Why a spine and not a flowchart

Arbitrary control flow needs edge routing, which needs a graph layout engine,
which is a third-party dependency ([N1](../CLAUDE.md)) and a large pile of code
that would mostly draw diagonal lines. A vertical spine with loops as left-hand
return rails covers what player solutions actually look like — sequence, loop,
branch, return — and stays readable in eighty columns.

## Rules the drawing follows

| Rule | Why |
| --- | --- |
| A compound statement owns its **header line only** | Its body is drawn as its own boxes. If the loop owned every line in its body, the token would light two boxes at once — a false claim about where control is, not just a drawing bug |
| A simple statement owns **every line it spans** | A call broken across four lines is one box, and the trace may report any of those lines |
| An `elif` gets **no `else` box** | An `elif` is an `If` inside `orelse`; drawing "else" in front of it shows a step the player never wrote. Same reasoning as the profiler's nesting metric (D65) |
| A step inside another function **keeps the last box lit** and says `in helper()` | Dropping it would make a helper call look instantaneous, and a solution that hides its work in a helper is exactly the one whose cost needs showing |
| A loop counts an iteration when control **re-enters its header** | Visits are not laps: moving around inside the body is one iteration |
| Nested boxes **share a right edge** | Nesting reads as nesting only if the boxes line up on one side |

## Where it runs

Both: `vibecoder vision` on demand, and inside the score reveal — it plays after
the test results and before the axes land, so you watch the machine work and
then see what it scored.

The reveal is the hottest path in the product, so the wiring is bounded rather
than trusted:

| Guard | Value | Why |
| --- | --- | --- |
| Time budget | 2.5 s | Between "did something happen" and "get on with it". A player grinding attempts never waits on it |
| Frame cap | 36 | A trace runs to 400 steps. Racing all of them inside the budget is a blur, so frames are **sampled** instead |
| Opt out | `--no-vision` | And `VIBECODER_NO_ANIM`, which the whole product already honours |
| Never raises | — | Nothing decorative may be able to break the reveal. No trace, code that will not parse, no function: it is silent |

Sampling is honest in a way that simply shortening the delay is not. Every frame
carries state computed over the **whole** trace before any sampling, so a kept
frame's loop counter is the true count at that instant rather than a count of
the frames that survived. The step number jumping from 40 to 52 is the reader's
cue that instants were skipped.

When the stream cannot animate — a pipe, a CI log, `VIBECODER_NO_ANIM` — the
`vision` command prints a single still frame instead. A recording of cursor
movement is not a useful artifact, and escape codes in a log file are a bug.
Unicode is a capability of the stream and colour is a capability of the
terminal, so a UTF-8 pipe still gets box-drawing characters and no escapes.

**The reveal prints nothing at all in that case.** The still frame exists
because somebody asked to see the machine; the reveal is a live flourish, and
adding twenty lines of drawing to every CI log and piped transcript is a change
nobody asked for. A piped `play` is byte-identical to what it was before this
landed.
