# The presentation layer

Everything VibeCoder draws goes through [`vibecoder/ui.py`](../vibecoder/ui.py).
No other module emits an escape sequence, and `cli.py` contains none at all.

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

## Known gaps

- The renderer is a module-level singleton in `cli.py`. Fine today; a web
  front-end or an output-capturing test would rather inject one (Q8 in
  [S002](../journal/2026-08-08-S002-presentation.md#open-questions)).
- Animation timing is fixed at roughly 0.35s per axis, unvalidated against a
  real player over many levels (Q9).
- No `curses`. The game prints; it does not own the terminal. That keeps the
  same code path working when output is a pipe, which `curses` could not do.
