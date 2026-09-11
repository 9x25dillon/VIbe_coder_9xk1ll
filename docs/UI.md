# The presentation layer

Everything VibeCoder draws **in lines** goes through
[`vibecoder/ui.py`](../vibecoder/ui.py), and `cli.py` contains no escape
sequence at all — `showcase | grep -c $'\033'` prints `0`, and that is the
half of this rule which is checked.

The full-screen stack is the documented exception, and has been since T7:
`term.py` owns the terminal mode, `screen.py` diffs a cell grid, and the
applications that compose into a `Screen` — [`editor.py`](../vibecoder/editor.py)
and [`repair.py`](../vibecoder/repair.py) — request cell styles through `Renderer.style()`,
because a grid painted by cell damage cannot be routed through a line
renderer. They pay the same price in return: composition is pure, frames are
asserted as plain text, and `Depth.NONE` yields no escapes at all. This
paragraph used to claim no other module emitted one, which stopped being true
the moment the editor shipped.

## The one rule

**Colour is decoration. Layout is content.**

Every element computes its plain-text layout first and applies colour last. The
consequence is the guarantee the whole module rests on:

> Escape-stripped output is byte-identical at every colour depth.

`tests/test_ui.py::TestDepthInvariance` asserts this for eleven elements across
all four depths. It is what lets every other test compare readable text instead
of escape soup, and it is why a change that alters visible text between depths is
a bug even when it looks better.

That rule has already cost one nicer-looking design: badges render as `[PASS]`
everywhere rather than as a background-filled pill when colour is available. See
[M4 in S002](../journal/2026-08-08-S002-presentation.md#m4--a-background-filled-badge-is-just-a-nicer-looking-badge).

## Capabilities

`detect(stream)` returns what the target can actually take:

| Field | Meaning |
| --- | --- |
| `depth` | `NONE` / `ANSI16` / `ANSI256` / `TRUECOLOR` |
| `unicode` | Whether the stream's encoding is UTF-8 |
| `animate` | Real TTY **and** `VIBECODER_NO_ANIM` unset |
| `width` | Terminal columns, or 80 when undetectable |

Resolution order for colour, highest priority first:

1. `NO_COLOR` set (to anything) → `NONE`. A user who sets this means it, so it
   beats everything below, including `FORCE_COLOR`.
2. `FORCE_COLOR` set → `1`/`2`/`3` select the depth. For CI systems that render
   escape codes despite not being a TTY.
3. Not a TTY, or `TERM=dumb` → `NONE`.
4. `COLORTERM` is `truecolor`/`24bit` → `TRUECOLOR`.
5. `TERM` contains `256` → `ANSI256`.
6. Otherwise → `ANSI16`.

Use `PLAIN` for deterministic output — it is what tests construct against.

## Elements

| Method | Draws |
| --- | --- |
| `gauge(value, width, maximum, rgb)` | A bar; colour tracks value unless overridden |
| `gradient_gauge(...)` | A bar where each cell is coloured by its own position |
| `stars(count)` | `★★☆` |
| `sparkline(values)` | A one-line series chart |
| `rule(title, width)` | A titled horizontal rule |
| `box(lines, title, width)` | A bordered panel |
| `badge(text, rgb)` | A bracketed label |
| `banner()` | The block-capital title |
| `axis_row(label, value, weight, detail)` | One line of the score breakdown |
| `health_bar(current, maximum)` | Boss health — built for [T3](trajectories/T3-boss-engine.md) |
| `level_map(entries)` | World progression, nodes and stars |
| `bar_chart(items)` | Labelled horizontal bars, used by the Vibe Vector |

Animation helpers (`reveal_gauge`, `typewriter`, `star_burst`) write to the
stream rather than returning strings. Each falls back to printing the finished
output when animation is unavailable, so a piped run produces the identical
final transcript.

## Adding an element

1. **Take `width` as a parameter.** Never call `get_terminal_size()` inside an
   element; the caller decides. This is what makes it testable at any size.
2. **Build the plain string, then paint.** If you find yourself interleaving
   escape codes with layout arithmetic, the element will not be
   depth-invariant.
3. **Give every glyph an ASCII fallback** in `GLYPHS`, and reach for it through
   `self.glyph(name)`. The fallback must be the same width as the Unicode
   version or the layout shifts.
4. **Add it to `TestDepthInvariance`** and, if it has a fixed width, to
   `TestWidth`.
5. **Add it to `showcase`** so it can be eyeballed.

## Seeing it

```bash
python3 -m vibecoder.cli showcase              # every element, plus detected caps
python3 -m vibecoder.cli showcase | cat        # the degraded path
NO_COLOR=1 python3 -m vibecoder.cli showcase   # colour off on a terminal
FORCE_COLOR=1 python3 -m vibecoder.cli showcase  # what a 16-colour terminal sees
python3 -m vibecoder.cli levels --map          # world map
```

The fastest correctness check is `showcase | grep -c $'\033'`. It must be zero.

## The editor

[T7](trajectories/T7-interactive.md) extends this layer from *drawing* to
*interacting*. The elements above still render into a scrolling transcript;
the editor renders into a fixed grid instead ([`screen.py`](../vibecoder/screen.py))
and emits only the cells that changed.

The one rule carries over unchanged. `Editor.style()` returns an empty prefix
at `Depth.NONE`, so an uncoloured frame contains the same characters in the
same columns as a coloured one — asserted by
`tests/test_editor.py::TestDegradation`, which compares every row's width
across capabilities. Rule 3 above matters even more here: a double-width glyph
in the editor chrome shifts every cell to its right, so
`tests/test_screen.py::TestWidth` pins the column arithmetic and every glyph
added to `GLYPHS` for the editor is a narrow character.

One deliberate divergence. `Renderer.paint` suppresses *all* attributes at
`Depth.NONE`, including bold. The editor does not: it still emits reverse video
there, because the block cursor is drawn with it and suppressing it would leave
a terminal running under `NO_COLOR` with no visible cursor. The `NO_COLOR`
convention asks for colour to be withheld, and reverse video is not colour.
`tests/test_editor.py::TestDegradation::test_a_plain_frame_still_draws_a_cursor`
holds that line.

```bash
python3 -m vibecoder.cli edit w2-l1-revenue    # needs a real terminal
```

## Known gaps

- The renderer is a module-level singleton in `cli.py`. Fine today; a web
  front-end or an output-capturing test would rather inject one (Q8 in
  [S002](../journal/2026-08-08-S002-presentation.md#open-questions)).
- Animation timing is fixed at roughly 0.35s per axis, unvalidated against a
  real player over many levels (Q9).
- No `curses`. The game prints; it does not own the terminal. That keeps the
  same code path working when output is a pipe, which `curses` could not do.

## Terminal cockpit (S038)

The shared [cockpit helpers](../vibecoder/cockpit.py) own bounded text regions,
column-aware clipping, prose wrapping, headers, and scrollable inspectors.
Editor and repair styles now delegate to `Renderer.style()`. The palette uses
cool cyan for focus, neutral text and rules, green for success, amber for
attention, red for failure, and gold for rewards. Background and font remain
the terminal user's choice.

- **Campaign:** `vibecoder levels --browse`. Up/down selects, Enter opens the
  level editor or live boss, and quitting the challenge returns to the browser.
  `ctrl-o` opens full details; Escape returns or leaves the browser. `NEXT`
  means the first uncleared campaign level, not an adaptive recommendation.
  `levels --map` remains a plain transcript, with every level named and commands
  for the next level and each boss.
- **Editor:** code stays primary. At 110 columns the objective sits alongside
  it; smaller terminals use `ctrl-o` for a full-width objective. `ctrl-g` opens
  help. Arrow keys and PgUp/PgDn scroll these views without editing source;
  Escape returns to code. Examples remain in authored briefs rather than
  exposing hidden test inputs. The source scrolls horizontally with the cursor.
- **Feedback:** verdict, first failure, advice, and score occupy stable bottom
  rows. Run and quit controls remain visible when a hint or error arrives.
  `ctrl-p` toggles the optional rhythm display. Successful runs show the score
  change from the preceding scored run in the current editor session.
  Accuracy, Solve time, and Efficiency are presentation labels for Accuracy,
  Speed, and Functional; no weights or measurements changed.
- **Bosses:** animated live fights use the machine view with persistent HP,
  repairs, encounter progress, and recorded values. `q` stops the fight.
  A live event count never claims to know the final trace length. The terminal
  is released before the repair pane opens; repair receives the current
  resources and authored objective. `ctrl-o` expands the error and values.
  Piped and reduced-motion fights keep their line transcript.
- **Results:** the verdict and total precede detailed axes. Status uses a
  compact wordmark, with the block logo retained in the showcase.

Supported geometry remains 48 columns by 12 rows. Color depths share identical
text and layout; ASCII fallbacks and `NO_COLOR` remain supported. Read-only
inspectors display a position and scroll affordance when content exceeds the
viewport; sidebar previews explicitly say `ctrl-o expand`.

[View the rendered preview](visual-overhaul.svg). These are illustrative sample
states, generated through the actual application composers. Regenerate with
`python3.11 tools/preview_ui.py` from the repository root. The sample terminal
background is for the preview only.
