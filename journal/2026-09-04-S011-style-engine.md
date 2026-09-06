# S011 — The profiler reads its own code, and does not like it

**Date:** 2026-09-04 · **Duration:** — · **Trajectory:** T4 (profiler) ·
**Competency band:** `Create` ·
**Data:** [`data/sessions/2026-09-04-S011.json`](../data/sessions/2026-09-04-S011.json)

## Objectives

| # | Objective | Result |
| --- | --- | --- |
| 1 | The profiler reads style signals it was blind to | ✅ met |
| 2 | A profile says something a person recognises, not only numbers | ✅ met |
| 3 | Two differently-written codebases get different descriptions | ✅ met |
| 4 | The world map says where you are *and* where to go | ✅ met |
| 5 | A cleared level leads somewhere | ✅ met |

## What was built

### The style engine

The profiler read eleven patterns and reported class naming as **0% PascalCase
for a codebase containing thirty-three classes**. That was not a display bug:
`_analyse_tree` never called `_naming_style` on a `ClassDef` at all.

Leaving them out was defensible and wrong in an interesting way. `PascalCase`
is correct for a class and wrong for a function, and they are the same token
shape, so pooling them into one histogram cannot tell a well-named class from a
Java-style function. Excluding classes avoided the conflation by discarding the
signal. **Conventions are now judged per identifier kind** — classes against
`PascalCase`, functions against `snake_case`, module constants against
`SCREAMING_SNAKE` — and a kind the codebase has none of is *absent* rather than
0%, because telling somebody they name every class wrongly when they have
written none is worse than saying nothing.

Twelve new detectors: `walrus`, `match_statement`, `dataclass`, `enumerate`,
`zip`, `builtin_aggregate`, `generator_function`, `nested_function`,
`star_args`, `keyword_only_args`, `property`, `static_or_class_method`,
`slots`, `global_statement`, `ternary`, `percent_format`, `str_format`. Several
are narrow on purpose: `percent_format` fires only when the left side of a `%`
is literally a string, so arithmetic modulo is not miscounted, and `str_format`
only on a literal receiver, so `logger.format(...)` is not mistaken for
`"{}".format(...)`.

Three new measurements the engine had no way to express:

- **Nesting depth** — whether somebody returns early or keeps stepping right.
- **A complexity distribution** — median and p90 beside the max, because
  `max_complexity` is one function on a bad day and says nothing about the
  usual one.
- **Comment density** — previously discarded while counting code lines.

And a **style signature**: a few readable traits derived from the whole vector.
`docstring_ratio 0.43` tells a player nothing about themselves. The signature
for this repository is *"strongly typed / comprehension-first / f-string era /
shallow nesting"*, and for the standard library's `json` it is *"untyped /
loop-first / %-format era / long functions"*. Both are recognisable, which is
the test that matters: a description you can argue with is one you looked at.
Every threshold is a judgement about style and never about quality, because a
signature that reads as a scolding is one people stop running.

### The map, and what comes after a win

`levels --map` drew nodes and stars and never said which level was which, so
the answer to "what do I play next" was to close the map and run `levels`. It
now carries a star tally per world and points at the first uncleared level by
name. A finished world says so.

Clearing a level used to end at the shell prompt. It now names the level that
follows and the first sentence of its brief, marks the end of a world, and
marks the end of the campaign.

## Evidence

```
$ python3 -m unittest discover -s tests
Ran 612 tests in 109.323s — OK

$ python3 -m vibecoder.cli verify --seeds 3
36/36 reference runs clean

$ python3 -m vibecoder.cli showcase | grep -c $'\033'
0

the engine discriminating, one line per codebase:
  vibecoder   typed=98%  nest=0.9  cx p90=9   -> strongly typed / comprehension-first / f-string era / shallow nesting
  json        typed=0%   nest=1.5  cx p90=22  -> untyped / loop-first / %-format era / long functions
  tkinter     typed=0%   nest=0.3  cx p90=3   -> untyped / object-oriented / %-format era / shallow nesting

profiling this package, before and after the refactor below:
  max complexity  73 -> 29        max nesting  5 -> 4
```

| Claim | Evidence | Verdict |
| --- | --- | --- |
| Class names are now judged | `TestConventions`, PascalCase and snake_case classes | verified |
| Class names do not pollute the naming histogram | `test_class_names_do_not_pollute_the_naming_histogram` | verified |
| A kind with no instances is absent, not 0% | `test_a_kind_with_no_instances_is_absent_rather_than_zero` | verified |
| An `elif` chain counts as one level | `test_an_elif_chain_stays_flat` | verified |
| A nested function keeps its own nesting budget | `test_a_nested_function_keeps_its_own_budget` | verified |
| Complexity is reported as a distribution | `TestComplexityDistribution`, median 1 / max > 10 | verified |
| Arithmetic modulo is not counted as formatting | `test_arithmetic_modulo_is_not_formatting` | verified |
| `obj.format()` is not counted as `str.format` | `test_a_format_method_on_an_object_is_not_str_format` | verified |
| A `yield` in a closure does not mark the outer function | `test_a_yield_in_a_closure_does_not_make_the_outer_a_generator` | verified |
| The dispatch refactor dropped no existing detector | `test_the_original_detectors_still_fire` | verified |
| Two differently-written codebases differ | `test_the_two_codebases_do_not_share_a_signature` | verified |
| No signature trait contains a comma | `test_no_trait_contains_a_comma` | verified |
| The map names the next uncleared level | `TestTheWorldMapGuides`, arrow position asserted | verified |
| The map layout is identical without Unicode | `test_the_layout_is_identical_without_unicode` | verified |
| A clear names what follows | `TestWhatComesNext`, 6 tests | verified |
| The signature is *accurate* about a stranger's codebase | judged by eye on five stdlib packages | `UNVERIFIED` — plausible, not measured |

## Misconceptions and corrections

### M22 — The profiler was blind to class naming by oversight

**Believed:** `_analyse_tree` forgetting to classify `ClassDef` names was a
plain omission, and the fix was one line adding them to the same histogram as
everything else.

**Revealed by:** Writing that line and looking at the result. `PascalCase`
jumped to a large share, and the number became meaningless: it now mixed
"correctly named classes" with "functions named the Java way", which are
opposite verdicts wearing the same token shape.

**Corrected to:** The omission was avoiding a real conflation, badly. Judging
conformance *per kind* keeps both signals — and the display had to change too,
because a `NAMING` block showing `PascalCase 0%` directly above `classes are
PascalCase 100%` is a contradiction on screen even when both numbers are right.

**Cost:** ~15 minutes. Worth recording that the one-line fix passed every test
that existed and would have shipped a worse metric than the bug.

### M23 — A profiler's own report is for other people's code

**Believed:** The enhancement was done when the detectors worked. The engine
reads codebases; it is not a judge of this one.

**Revealed by:** Running it on `vibecoder/` and reading the output. Max
complexity had gone from 39 to **73**, and the worst function in the codebase
by a factor of two was `_analyse_tree` — the function I had just doubled in
size with a twenty-branch `elif` chain.

**Corrected to:** Replaced the chain with a dispatch table keyed on node type.
Max complexity fell to 29 and max nesting from 5 to 4, and the new
`test_the_original_detectors_still_fire` guards the refactor. A profiler whose
own report condemns it is not one to trust, and the tool caught this before I
did.

**Cost:** ~20 minutes, and it is the most useful twenty minutes in the session.

### M24 — `max_nesting: 22` was a deep function somewhere

**Believed:** The first nesting implementation reported a maximum depth of 22
in this codebase, which read as a real finding about some horrible function.

**Revealed by:** Looking for the function. It was `_analyse_tree` again — and
its `elif` chain is *one* level to a reader. Each `elif` is an `If` inside the
previous one's `orelse`, so an AST walk sees a 22-deep staircase where a person
sees a flat list.

**Corrected to:** Nesting is measured over *statements* rather than by walking
the tree, and an `elif` chain counts once. The metric is about the indentation
a person looks at, so the AST shape is the wrong thing to count.

**Cost:** ~10 minutes. The number was absurd enough to check; a plausible wrong
number — 4 instead of 3 — would have shipped.

## Friction

- Test file names cannot be keyword arguments: `self.profile(a_py=...)` writes
  a file called `a_py`, which the `*.py` globber never finds, so every
  assertion silently measured an empty directory and thirty-five tests failed
  at once. The existing suite used `**{"a.py": ...}` and I did not look first.
  Added a `one()` helper to the base class so the next person cannot repeat it.
- `style_signature` labels are joined with `/` for display, and two of them
  contained commas — which read as extra traits. Caught by a test written for
  the purpose rather than by looking, which is the right way round.

## Decisions

| # | Decision | Alternatives considered | Rationale | Reversible? |
| --- | --- | --- | --- | --- |
| D63 | Conventions are counted per identifier kind | Pool class names into `naming`; keep excluding them | The same token shape is a correct class and an incorrect function. One number cannot say which | yes |
| D64 | A kind with no instances is absent, not 0% | Report 0% | "You name every class wrongly" is a bad thing to tell somebody with no classes | yes |
| D65 | Nesting is a statement walk, and `elif` counts once | `ast.walk` depth | The metric is about the indentation a person sees; the AST disagrees with the screen exactly here | yes |
| D66 | Complexity is reported as median, p90 and max | Max alone, as before | Max is one function on a bad day. The distribution describes the codebase | yes |
| D67 | `_analyse_tree` is a dispatch table | The `elif` chain; a visitor class | Its own metrics condemned the chain. A table is flat, and adding a detector no longer adds a branch | yes |
| D68 | Detectors are narrow rather than eager | Match `%` and `.format` anywhere | A profile is read as fact. `x % 7` is not string formatting and `logger.format()` is not `str.format` | yes |
| D69 | The signature describes style, never quality | Score the codebase | The profiler exists so the game can meet somebody where they are. A report that reads as a scolding stops being run | yes |

## Handoff

- **State:** The style engine reads 21 patterns plus conventions, nesting,
  complexity distribution and comment density, and renders a style signature.
  612 tests green unpinned, `verify` clean on 36 reference runs, `showcase`
  prints zero escapes in a pipe.
- **⚠ Use Python 3.11 on this machine** — see M5 in S003. Unchanged.
- **Next action:** unchanged and untouched by this session: **T2 W4** (GitHub
  OAuth ingestion) is blocked on a registered OAuth application and the
  client-versus-server profiling decision; **T2 W5** (`.zip` ingestion with a
  decompression bomb guard) is unblocked.
- **Blockers:** none introduced here.
- **Context required:** N3 still holds and was not weakened — every signal
  added this session is pure `ast` walking and nothing executes analysed code.
  D63 before touching `naming` or `conventions`; D65 before changing the
  nesting metric.

## Open questions

| # | Question | Owner trajectory | Status |
| --- | --- | --- | --- |
| Q40 | `VibeVector` gained six fields. `from_json` drops unknown keys and new fields have defaults, so old profiles still load — but a profile written today and read by an older build silently loses signals. Is that the migration story T2 W7 wants, or does the vector need a version? | T2 | open |
| Q41 | The signature thresholds (0.7 for "strongly typed", 2.5 for "deeply nested") were chosen by profiling five stdlib packages and this repository. That is six data points. Do they hold on real application code, and how would we know without collecting profiles we have promised never to collect? | T4 | open |
| Q42 | `_record_constants` only judges module-level assignments, so a class-level constant is not counted. Correct today, but a codebase that keeps its constants on classes gets a `constant` conformance built from very few names. Should the sample size be reported next to the ratio? | T4 | open |
| Q43 | Six of the new patterns map to no tag, so they enrich the display and cannot influence level selection. Is that the right split, or should `walrus`/`match_statement` recommend a "modern Python" level that does not exist yet? | T4 | open |
