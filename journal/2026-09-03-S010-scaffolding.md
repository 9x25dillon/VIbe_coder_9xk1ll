# S010 — Telling a beginner what actually happened

**Date:** 2026-09-03 · **Duration:** — · **Trajectory:** T4 (coaching) ·
**Competency band:** `Evaluate` ·
**Data:** [`data/sessions/2026-09-03-S010.json`](../data/sessions/2026-09-03-S010.json)

## Objectives

| # | Objective | Result |
| --- | --- | --- |
| 1 | A failing player is shown the input that broke their code | ✅ met |
| 2 | One bug is reported once, not once per test case | ✅ met |
| 3 | A tip never asserts a cause it did not check | ✅ met |
| 4 | A stuck player can get unstuck without leaving the game | ✅ met |

## What was built

[S009](2026-09-03-S009-beginner-world.md) built the on-ramp. This is the other
half: what the game says when a beginner gets it wrong. The starting point,
played rather than read:

```
✘ FAIL  mixed  IndexError: list index out of range
✘ FAIL  empty_list  IndexError: list index out of range
...five more identical lines...

VIBE TIPS
  ▸ Accumulating with `+=` in a loop is what `sum()` does
```

Three separate failures in one screen. The player is never shown the **input**,
so they cannot reproduce the failure by hand — which is the first thing anyone
does. One bug is reported seven times. And the only advice offered is about
elegance, to somebody whose program does not run.

**`WHAT WENT WRONG`** expands the first failing case only: what it was given,
what was expected, what came back — or what was raised. Later failures are
usually the same bug seen again, so identical errors collapse to *"The other 6
cases stopped the same way"*. Values are shortened in the middle rather than
truncated, because the ends of a list are what identify it: `[0, 1, 2 ... 399]`
says more than the first eighty characters do.

**Tips now have a kind.** `CORRECTNESS` rules are about whether the code is
right; `POLISH` rules are about whether working code is idiomatic. When nothing
passed, only correctness rules may speak — and if none matches, the game says
nothing, which is a better answer than filling the space.

That left the broken program above with no tip at all, because
`range_len_indexing` matches `range(len(xs))` and the bug was
`range(len(xs) + 1)`. That is not a near-miss, it is a *different bug*: the
off-by-one that walks one past the end. It now has its own narrow rule, and the
player gets the diagnosis instead of a `sum()` suggestion:

> `range(len(xs) + 1)` takes one step past the end of the list, so the last
> index does not exist. A list of 4 items has indexes 0 to 3, and
> `range(len(xs))` stops in the right place.

**Q33 is answered.** The efficiency tip claimed *"look for work being repeated
inside a loop that could happen once outside it"* on every high op ratio. On
`w1-l4-double` nothing is loop-invariant — the cost is `append` versus a
comprehension — so the tip sent a beginner hunting for a bug that was not
there. The op count says *how much* work was done and never *why*, and the rule
had not looked. It now names the usual causes as possibilities.

**Hints** are `Level.hints`, revealed one per failed attempt after the first.
The first attempt never earns one: being stuck for a minute is the part of the
exercise that teaches. Each beginner level has three, laddering from a nudge to
the shape of the answer. `vibecoder play` reprints the whole earned ladder,
because the earlier rungs have scrolled away and the sequence is the point; the
editor's one status row shows the newest.

## Evidence

```
$ python3 -m unittest discover -s tests
Ran 553 tests in 83.820s — OK

$ python3 -m vibecoder.cli verify --seeds 3
36/36 reference runs clean

$ python3 -m vibecoder.cli showcase | grep -c $'\033'
0

the same broken submission, before and after:
  before:  7 identical FAIL lines, no input, tip about sum()
  after:   input shown, "The other 6 cases stopped the same way",
           tip naming range(len(xs) + 1) as the off-by-one
```

| Claim | Evidence | Verdict |
| --- | --- | --- |
| The failing input is shown | `TestTheFailureBlock::test_the_input_is_shown` | verified |
| Nothing is printed when everything passed | `..._nothing_is_printed_when_everything_passed` | verified |
| One bug is reported once | `..._identical_errors_are_collapsed_into_one_line`, asserts a single copy | verified |
| Mixed failures are counted, not collapsed | `..._mixed_failures_are_counted_rather_than_collapsed` | verified |
| Long values keep both ends | `test_both_ends_survive` | verified |
| A broken program gets no style advice | `test_a_broken_program_is_not_given_style_advice` | verified |
| A broken program still gets correctness advice | `test_a_broken_program_still_gets_the_off_by_one` | verified |
| Working code still gets polish advice | `test_a_working_program_still_gets_polish_advice` | verified |
| Silence is allowed when no rule matches | `test_silence_is_allowed_when_no_correctness_rule_matches` | verified |
| The off-by-one rule does not fire on correct code | `test_a_correct_range_len_is_not_flagged_as_off_by_one` | verified |
| The efficiency tip no longer asserts a cause | `TestTheEfficiencyTipClaimsOnlyWhatItChecked` | verified |
| The first attempt earns no hint | `test_the_first_attempt_earns_nothing`, all beginner levels | verified |
| Hints arrive one per failure | `test_hints_arrive_one_per_failure` | verified |
| A hint never pastes the reference | `test_no_hint_simply_hands_over_the_reference` | verified |
| The editor shows a hint from the second attempt | `test_a_failed_run_offers_a_hint_from_the_second_attempt` | verified |
| A passing run never shows a hint | `test_a_passing_run_never_shows_a_hint` | verified |
| Output is identical at every colour depth | assertions run on escape-stripped text; `showcase` prints 0 escapes in a pipe | verified |
| The hints are pitched right for a real beginner | no beginner has read them | `UNVERIFIED` — same limit as S009 |

## Misconceptions and corrections

### M20 — Suppressing the wrong tip is the same as giving the right one

**Believed:** The zero-score run's problem was that a `sum()` tip fired on a
broken program, so gating polish rules behind "something passed" fixed it.

**Revealed by:** Doing exactly that and re-running. The player now got *no*
tip — better, but the submission contained `range(len(numbers) + 1)`, which is
a specific, diagnosable, extremely common beginner bug that the game could name
outright. The existing rule missed it by one AST node.

**Corrected to:** Two changes, not one. Suppression stops the wrong answer;
only a new rule supplies the right one. Stopping at the gate would have looked
like a fix in the diff and left the beginner with a blank space where the
diagnosis belongs.

**Cost:** ~10 minutes. The useful part is that the intermediate state passed
every test I had written and was visibly worse for the player than the state
after, which is an argument for playing the thing between each change rather
than at the end.

### M21 — A test case named after a lesson teaches that lesson

**Believed:** `w1-l2-bigger`'s `equal_values` case would catch a beginner
writing `>` where `>=` belongs — that was the level's stated reason to exist,
in its docstring and in S009's journal entry.

**Revealed by:** Playing the level with exactly that mistake, per §7's
instruction to play a level after its contract tests pass. It passes: for a
function returning the larger of two numbers, a tie returns the same value
whichever branch runs, so the case cannot discriminate.

**Corrected to:** The case pins that a tie returns a value rather than `None`,
which is worth having and is not what was claimed. The tie that genuinely
discriminates is in `w1-l5-longest`, where the answer is a *position*: `>=`
there returns the last longest word, and `tie_keeps_the_first` catches it. The
docstring now says what the case proves. S009's entry is corrected in place
because it was written in this same sitting and had not yet been relied on.

**Cost:** ~5 minutes. It shipped in the previous commit, which is the part
worth noting: the contract tests were green the whole time, because
well-formedness and pedagogy are different properties and only one of them is
mechanically checkable.

## Friction

- No test file existed for `cli.py`, since the architecture rule is that
  nothing imports it. Nothing in the *package* importing it is the rule; a test
  importing it creates no cycle, because nothing imports the test. Said out
  loud in `tests/test_cli_output.py`'s docstring so the next reader does not
  have to re-derive it.
- The suite ran in 84 s here against 140 s earlier today, on the same machine
  with the same tests. The spread is Docker cold-start, so the living docs now
  quote a range and say why, rather than a number that goes stale between two
  runs an hour apart.

## Decisions

| # | Decision | Alternatives considered | Rationale | Reversible? |
| --- | --- | --- | --- | --- |
| D57 | Only the first failing case is expanded | Expand all; expand none | Later failures are usually the same bug again. Eight copies teach nothing the first did not, and the pass/fail list above still names every case | yes |
| D58 | Tip rules are tagged correctness or polish | A flat list with an ordering; a hard limit when nothing passes | The limit was arbitrary and still let the wrong rule win. The tag says *why* a rule may speak, which is the actual distinction | yes |
| D59 | Silence is a valid tip outcome | Always emit something | A filler tip on a broken program is the behaviour being removed; re-adding it under a different name would be worse | yes |
| D60 | `range(len(xs) + 1)` gets its own narrow rule | Broaden `range_len_indexing` | They are different bugs with different fixes. Broadening would make one message serve two causes and be vague about both | yes |
| D61 | The first attempt earns no hint | Hint immediately; hint on request | Being stuck briefly is what does the teaching. A hint on attempt one replaces the exercise | yes |
| D62 | `play` reprints the whole ladder, the editor shows the newest | Both show one; both show all | The earlier rungs have scrolled away in a terminal but the editor has one status row. Different constraints, same ladder | yes |

## Handoff

- **State:** Both halves of the beginner request are landed. 553 tests green
  unpinned, `verify` clean on 36 reference runs, `showcase` still prints zero
  escapes in a pipe. 12 levels across 3 worlds; World 1 has hints, the later
  worlds declare none.
- **⚠ Use Python 3.11 on this machine** — see M5 in S003. Unchanged.
- **Next action:** nothing outstanding on the beginner track. The trajectory
  queue is unchanged: **T2 W4** (GitHub OAuth ingestion), still blocked on a
  registered OAuth application and the client-versus-server profiling decision;
  **T2 W5** (`.zip` ingestion with a decompression bomb guard) is unblocked and
  exercises the same budgets.
- **Blockers:** none introduced here.
- **Context required:** D58 before adding a tip rule — a new rule must declare
  its kind or it silently defaults to `POLISH` and will not speak to a player
  whose code is broken. D61 before changing when hints appear.

## Open questions

| # | Question | Owner trajectory | Status |
| --- | --- | --- | --- |
| Q33 | Should the efficiency tip be conditioned on evidence of loop-invariant work, or reworded? | T4 | **answered** — reworded. The op count measures how much work happened and never why, so the rule now names causes as possibilities. Conditioning it properly would mean detecting loop-invariant work, which is a real analysis and not a tip rule |
| Q37 | A new tip rule defaults to `POLISH`, so forgetting the kind means it never speaks to a broken program — the quiet failure D36 warned about in another context. Should `kind` be required, the way `Source` is on `run_code`? | T4 | open |
| Q38 | Hints are static text per level. A player who fails three times for three *different* reasons gets the same ladder as one failing the same way three times. Should a hint be selected by what actually failed rather than by attempt count? | T4 | open |
| Q39 | `_echo` shortens with a middle ellipsis at 88 characters, chosen to fit an 80-column terminal. The editor and `play` have different widths available and neither passes its own. Should the cap follow the terminal? | T7 | open |
