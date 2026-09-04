# S009 — An on-ramp, and the world that had to move to make room

**Date:** 2026-09-03 · **Duration:** — · **Trajectory:** T1 (content) ·
**Competency band:** `Create` ·
**Data:** [`data/sessions/2026-09-03-S009.json`](../data/sessions/2026-09-03-S009.json)

## Objectives

| # | Objective | Result |
| --- | --- | --- |
| 1 | A person who has just installed Python can finish the first level | ✅ met |
| 2 | Each beginner level teaches the one idea the next level needs | ✅ met |
| 3 | An easy level is never worth fewer points than a hard one | ✅ met |
| 4 | Renumbering changes level identity and nothing else | ✅ met |

## What was built

The game opened on `w1-l1-revenue`, which asks a player to iterate a list of
dicts, filter on a threshold, multiply two fields, accumulate, and round —
five ideas at once, before the player has met any of them. There was nothing
below it. The request was to advance the game for very beginner coders, and
the honest finding is that the *scorer* was already kind: a plain `for` loop on
that level scores 96.5 and three stars, because practice mode drops Speed and
renormalises (the M1 fix). What was missing was content, not tuning.

**World 1, "First Steps", is six levels that assume nothing.** Each teaches one
idea and hands it to the next:

| Level | Teaches | Hands on |
| --- | --- | --- |
| `w1-l1-greet` | `return` gives a value back — it is not `print` | a function that produces something |
| `w1-l2-bigger` | `if`/`else`, and that ties need a decision | a comparison |
| `w1-l3-count` | a loop with a counter | repetition |
| `w1-l4-double` | building a *new* list, leaving the input alone | a list result |
| `w1-l5-longest` | the "best so far" variable | state across iterations |
| `w1-l6-tally` | counting into a dict | the dict World 2 assumes throughout |

The ladder is deliberate about where it ends. `w1-l6-tally` is `dict.get(key,
0)`, and the level immediately after it is the old first level, which needs
dicts on line one. The on-ramp meets the road rather than stopping short of it.

Each level's hand-written cases are the ones randomness will not produce: the
empty list, the tie, the value exactly equal to the boundary, the empty string.
`w1-l2-bigger` exists largely for its `equal_values` case — a beginner writes
`>` without thinking about the tie, and a hand-written case turns that into a
lesson rather than an intermittent mystery.

Only `w1-l4-double` declares a style goal (`uses_comprehension`), and only
because the player wrote the loop by hand in the level before. The idiom then
arrives as a shortening of something they already understand rather than as
syntax to memorise. Levels 1, 2, 3, 5 and 6 declare none: a beginner does not
need to be told their working code is unstylish.

### The renumbering

A beginner world could not be world 0, because `Level.multiplier` is
`1.0 + 0.1 * (world - 1)` and world 0 scores at **×0.9** — beginner levels
worth *less* than the levels above them, which inverts the thing the multiplier
exists to say. The alternatives were to floor the multiplier at 1.0, changing a
scoring rule, or to renumber. Renumbering was chosen because it leaves the
scoring rule untouched: the beginner world is world 1, "Data Wrangler" moved to
world 2, and "Algorithm Architect" to world 3.

`data/baselines/2026-09-03-beginner-world-baseline.json` supersedes the T1
baseline rather than editing it, per N6 — the old file's level ids no longer
exist, and only the newest baseline is read. The renumbered levels reproduce
their old op counts exactly, which is the evidence that renumbering touched
identity and nothing else.

## Evidence

```
$ python3 -m vibecoder.cli verify --seeds 3
36/36 reference runs clean            (was 18/18: 12 levels x 3 seeds)

$ python3 -m unittest discover -s tests
Ran 519 tests — OK

beginner-quality solutions, played:
  w1-l1-greet   "Hello, " + name + "!"        100.0 acc   118.9  ***
  w1-l4-double  explicit loop with .append    100.0 acc   101.7  ***  (+ comprehension tip)
  w1-l6-tally   if item in counts / else       77.0 fn    110.8  ***

op counts, renumbered levels, new baseline vs T1 baseline:
  w2-l1-revenue  442  == old w1-l1-revenue  442
  w2-l3-join    2184  == old w1-l3-join    2184
  w3-l3-wordfreq  75  == old w2-l3-wordfreq  75
```

| Claim | Evidence | Verdict |
| --- | --- | --- |
| Every new level's starter fails its own tests | `test_the_starter_is_not_already_the_answer`, 12 levels | verified |
| Every new reference passes every variant | `test_every_reference_solves_every_variant`, seeds 1/2/3/7 | verified |
| Every reference meets its declared style goals | `test_every_reference_meets_its_own_style_goals` | verified |
| Seeds reproduce, and different seeds differ | `TestVariants`, all 12 levels | verified |
| Each level has at least four cases with hand-written edges | `test_every_variant_has_edge_cases` | verified |
| An easy level is never worth less than a hard one | `test_multiplier_grows_with_world`: w1 1.0, w2 1.1, w3 1.2 | verified |
| Renumbering changed identity only | new baseline's op counts match the T1 baseline for all six moved levels | verified |
| A beginner's solution is rewarded, not punished | three beginner solutions played; all three stars | verified |
| The scorer needed no tuning for beginners | naive loop on the old first level scores 96.5, three stars | verified |
| The beginner ladder is the right difficulty for a real beginner | no beginner has played it | `UNVERIFIED` — see below |

## Misconceptions and corrections

### M17 — "Beginner-friendly" meant the scoring was too harsh

**Believed:** A novice writing an explicit loop would be punished by the
Functional axis, which compares against an idiomatic reference, and by a Speed
axis with a 180-second par. Making the game beginner-friendly therefore meant
retuning curves and par times.

**Revealed by:** Doing what M1 says to do and scoring a *bad* solution rather
than reasoning about it. A beginner-style loop on `w2-l1-revenue` scores 96.5
and three stars: practice mode drops Speed entirely and renormalises the other
two, so Functional's 51.8 is diluted by Accuracy's 100 and the bonuses.

**Corrected to:** The barrier was never the scorer, it was that the first level
needed five concepts at once and nothing sat below it. The fix is content. Had
I retuned the curves as planned, I would have made the scoring less honest to
solve a problem it did not have.

**Cost:** None — the measurement came before the work. Recorded because the
plausible-sounding diagnosis was wrong and only a measurement said so, which is
the same shape as M1 and worth noticing twice.

### M18 — A new world can just be numbered 0

**Believed:** Adding a beginner world below world 1 meant calling it world 0,
which is the obvious name and changes nothing else.

**Revealed by:** Reading `Level.multiplier`, `1.0 + 0.1 * (world - 1)`, which
makes world 0 a ×0.9 multiplier. The beginner levels would have been worth less
than everything above them — a penalty for being a beginner, applied silently.

**Corrected to:** Renumber instead. The multiplier rule is untouched and no
level is worth less for being easy. The cost is that six level ids changed and
the T1 baseline had to be superseded, which is real but bounded and paid once.

**Cost:** ~20 minutes of renaming and reference-chasing. Cheap relative to
noticing it after players had banked scores against a ×0.9 world.

## Friction

- Level ids appear in living docs, in landed trajectory records and in
  journals. Only the living docs were updated: `T1-core-loop.md` names
  `w1-l3-join` inside an exit criterion's evidence column, and N7 forbids
  editing that. Historical records describe what was true when written, so
  they keep the old ids and will read oddly to someone who greps for a level.
  No mechanism distinguishes "an id in a live document" from "an id in a
  record", and one grep cannot tell them apart.
- `tests/test_levels.py` hard-codes two level ids, so renumbering broke exactly
  two tests. That is the registry contract working as intended, but it is worth
  noting they were the *only* two failures out of 519 — the contract tests
  iterate the registry, so twelve levels are covered by the same fifteen tests
  that covered six.

## Decisions

| # | Decision | Alternatives considered | Rationale | Reversible? |
| --- | --- | --- | --- | --- |
| D52 | The beginner world is world 1; existing worlds moved up | World 0 at ×0.9; floor the multiplier at 1.0 | Leaves the scoring rule untouched and never makes an easy level worth less. Floors are a scoring change (§12 says ask); world 0 is a silent penalty | expensive |
| D53 | A new baseline supersedes rather than edits the T1 one | Edit the T1 baseline's ids | N6. The old ids genuinely no longer exist, and only the newest baseline is read | yes |
| D54 | Five of six beginner levels declare no style goal | A goal on each | A beginner does not need to be told their working code is unstylish. The one goal lands where the player has just written the loop by hand | yes |
| D55 | Beginner levels carry a large random case | Small cases only | Functional needs somewhere for wasted work to show, and §7 asks for a variant where inefficiency costs something | yes |
| D56 | Par times are generous: 120s to 360s, rising with the ladder | The 180s default | Par is what Speed scores against, and a beginner reading a brief for the first time is not slow, they are new | yes |

## Handoff

- **State:** 12 levels across 3 worlds. World 1 "First Steps" is the beginner
  on-ramp. 519 tests green unpinned, `verify` clean on 36 reference runs.
  Old ids `w1-*` and `w2-*` now refer to different levels — see D52 before
  reading any journal entry written before this one.
- **⚠ Use Python 3.11 on this machine** — see M5 in S003. Unchanged.
- **Next action:** the second half of this request — **beginner scaffolding in
  the editor**: plain-language failure output naming the first failing case's
  input, expected and got; softer tracebacks; and a hint ladder revealed after
  repeated failures. One flaw is already identified: see Q33.
- **Blockers:** none. T2 W4's two blockers stand and are untouched by this.
- **Context required:** D52 before adding a world or touching `multiplier`;
  N6 before touching `data/baselines/`; §7 before adding a level.

## Open questions

| # | Question | Owner trajectory | Status |
| --- | --- | --- | --- |
| Q33 | The op-ratio tip says "look for work being repeated inside a loop that could happen once outside it" whenever the ratio is high, but on `w1-l4-double` nothing is loop-invariant — the cost is `append` versus a comprehension. A confidently wrong tip is worse for a beginner than no tip. Should the tip be conditioned on evidence of loop-invariant work, or reworded? | T4 | open |
| Q34 | Nothing enforces that a world's levels form a teaching order; `index` only orders them. The ladder in World 1 is a claim in a docstring. Is that worth a declared prerequisite, or is it over-formalising six files? | T4 | open |
| Q35 | Six of twelve levels are now tagged `basics`, which the vibe recommender uses for ordering. Does a profiler that sees an experienced developer correctly skip World 1, or will tag sparsity (T4's hazard) surface beginner levels to people who do not need them? | T4 | open |
| Q36 | Level ids appear in living docs, landed trajectories and journals, and only the first should be rewritten when ids change. Nothing distinguishes them mechanically. Worth a checked convention before the next renumbering? | T1 | open |
