# The Vibe Profiler

The profiler reads a codebase and produces a **Vibe Vector**: a statistical
fingerprint of how someone writes Python. That vector drives which levels the
game recommends and which coaching tips it considers relevant.

## What it does not do

It never executes the code it analyses. `profiler.py` is pure `ast` walking,
start to finish. Given that its input is other people's repositories — and that
[T2](trajectories/T2-sandbox.md) will point it at GitHub — this is a security
property, not a stylistic preference.

It also never persists source. The Vibe Vector is derived statistics; the code
it came from is discarded. That commitment is written into
[`data/README.md`](../data/README.md) as a rule about what may be stored.

## Running it

```bash
vibecoder profile ~/code/my-project      # human-readable
vibecoder profile ~/code/my-project --json > vibe.json
```

The result is saved into the player's profile and used automatically by
`vibecoder levels`.

## What it extracts

| Signal | How | Used for |
| --- | --- | --- |
| **Libraries** | Top-level module of every import | Content tags — `pandas` → `data`, `flask` → `web` |
| **Patterns** | AST node types: comprehensions, generators, lambdas, decorators, classes, f-strings, `with`, `try`, `map`/`filter`/`reduce`, recursion, type hints | Tags, plus tip relevance |
| **Exceptions handled** | `ExceptHandler` names, including bare `except:` | Which failure modes the player already thinks about |
| **Function length** | `end_lineno − lineno`, averaged | Calibrating level size |
| **Complexity** | Cyclomatic: 1 + branch points, counting each extra `BoolOp` operand and each comprehension `if` | Difficulty calibration |
| **Docstring ratio** | Documented functions ÷ total | Whether documentation goals are worth setting |
| **Naming** | Classifies every stored name and function name | Presentation, and detecting a house style |

Directories that are obviously not the player's own code (`.venv`,
`node_modules`, `__pycache__`, `build`, `site-packages`, …) are skipped, and
`__future__` is excluded from libraries — it says nothing about what someone
likes to build with.

Files that fail to parse are counted and skipped. A repository with one Python 2
file in it still profiles.

## Normalisation, and the bug that shaped it

Pattern values are all 0–1 so they compare across codebases of any size. **How**
they are normalised turned out to matter more than expected.

The first implementation used `min(1.0, occurrences / files)`. Self-profiling
reported exactly **100% for four separate patterns**, including `try_except` and
`fstring` — anything appearing more than once per file on average pinned to the
cap. The normalisation had destroyed precisely the signal it existed to expose,
and since saturated patterns cannot discriminate, every downstream tag decision
would have quietly degraded.

The fix splits the two cases:

- **File-level patterns** (comprehension, f-string, class, `try`, lambda, …) →
  *share of files containing the pattern*. Bounded by construction, and
  interpretable at any repository size.
- **Per-function patterns** (`decorator`, `type_hints`, `recursion`, `async`) →
  *share of functions*. "What fraction of your functions are decorated" is a
  meaningful quantity; "what fraction of your files contain a decorator" is not.

Self-profiling now gives a usable spread: type hints 97%, f-strings 89%,
comprehensions 78%, try/except 44%, classes 28%.

Full write-up: [M2 in S001](../journal/2026-08-08-S001-core-loop.md#m2--pattern-frequency-can-be-normalised-by-dividing-by-file-count).

## Tags

Libraries and patterns collapse into content tags, which are the only part of
the vector that level selection reads:

```
pandas, numpy, csv, polars     → data, tabular, numeric
requests, httpx, bs4, scrapy   → web, http, scraping
flask, fastapi, django         → web, server
itertools, functools, operator → functional
heapq, bisect, collections     → algorithms, datastructures
asyncio                        → async
```

A pattern earns its tag only above a threshold (35%), so one stray comprehension
does not make someone a functional programmer.

## Recommendation: gaps over comfort

```python
score = 0.4 × comfort + 0.6 × gap
```

where `comfort` is the share of a level's tags the player already uses, and
`gap` is the share they do not.

**The weighting leans toward gaps on purpose.** The stated goal of the Vibe
Vector in the design document is to *fill knowledge gaps* — a game that only
serves you what you are already good at is a leaderboard, not a teacher.
Comfort still carries 40% so the queue stays recognisable rather than throwing a
pandas-only player straight into async on day one.

Levels with no tags sort last. Without a profile, ordering falls back to
campaign order.

## What it deliberately does not measure

**Skill.** The Vibe Vector describes *habits*, not *ability*. Someone who uses
`pandas` in every file may still be bad at it.

Performance measurement is a separate model, deliberately kept separate, and it
belongs to [T4](trajectories/T4-adaptive.md). Merging the two is the most
tempting simplification available here and the most wrong: it would let the game
conclude you are good at something purely because you do it often.
