# Working agreement — VibeCoder

Claude Code loads this file into every session in this repository. It is the
operating procedure, not background reading. Where it conflicts with a general
habit, this file wins.

**What this project is:** a Python puzzle game that scores submissions on three
independent axes and adapts to how the player already writes code. Phase 0 is
complete and playable. See [`README.md`](README.md) for the product, this file
for how to work on it.

---

## 1. Start every session here

Do these three things **before writing any code**. They take under a minute and
they exist because the alternative is re-deriving state that is already written
down.

1. **Read the newest handoff.** `ls journal/` and open the latest entry; its
   `## Handoff` block states what is true now, the single next action, blockers,
   and what to read first. Do what it says unless the user overrides it.
2. **Read the trajectory** named in that handoff, in
   [`docs/trajectories/`](docs/trajectories/). Waypoints and exit criteria live
   there. Work is scoped to a waypoint, never to "improve the thing".
3. **Confirm the baseline is green:**
   ```bash
   python3 -m unittest discover -s tests      # 131 tests, ~4s
   python3 -m vibecoder.cli verify --seeds 3  # 18/18 reference runs clean
   ```
   If either is red before you change anything, say so and fix that first. Never
   build on a red baseline.

If the user's request does not map to a waypoint on the current trajectory, say
so in one sentence and proceed with what they asked. The plan serves the work.

---

## 2. Non-negotiables

These are invariants, not preferences. Each one has a reason and most have a
scar. Breaking one requires the user's explicit say-so **and** a journal entry.

| # | Rule | Why |
| --- | --- | --- |
| N1 | **No third-party dependencies.** Not in `vibecoder/`, not in `tests/`. | Every metric stays inspectable rather than borrowed, and the game runs anywhere a Python 3.10+ interpreter does. Adding one needs a journal entry justifying it. |
| N2 | **`_harness.py` never imports the `vibecoder` package.** | It runs as a standalone script in a separate interpreter. A broken game module must not be able to corrupt a submission run. |
| N3 | **The profiler never executes analysed code and never persists source.** | Its input is other people's repositories. Pure `ast` walking is a security property, not a style choice. |
| N4 | **Phase 0's sandbox is an isolation boundary, never described as a security one.** | It contains a learner's infinite loop. It does not contain an attacker. Do not run other people's submissions through it. |
| N5 | **An axis that cannot be measured honestly must not be scored.** | Drop it and renormalise. Never fake a value. This is the M1 scar — see §5. |
| N6 | **Files in `data/` are immutable once committed.** | Correct a record by adding one that supersedes it. Editing history is how a baseline stops being evidence. |
| N7 | **Exit criteria are never edited to match what was built.** | If they turn out wrong, that is a finding for the journal. Rewriting them destroys the only honest signal a trajectory has. |
| N8 | **Test suite green at every commit.** | It runs in four seconds. There is no excuse. |

---

## 3. Commands

```bash
# The two gates. Run both before saying anything is done.
python3 -m unittest discover -s tests
python3 -m vibecoder.cli verify --seeds 3

# Narrower loops while working
python3 -m unittest tests.test_scoring -v
python3 -m unittest tests.test_records            # docs, links, schemas, baseline
python3 -m vibecoder.cli verify --seeds 5 -v      # per-level ops and memory

# Play it. Contract tests prove a level is well-formed; only playing tells you
# whether it is any good.
python3 -m vibecoder.cli play w1-l1-revenue
python3 -m vibecoder.cli play w1-l3-join --solution /tmp/attempt.py --seed 1
python3 -m vibecoder.cli profile vibecoder        # self-profile as a smoke test
```

Set `VIBECODER_HOME` to a scratch directory when testing anything that writes
player state, so you never touch a real profile.

---

## 4. The three axes — do not conflate these

This is the single most common source of confusion in the codebase, and the
glossary calls it out for the same reason.

| Axis | Measures | Weight (level) |
| --- | --- | --- |
| **Accuracy** | Fraction of hidden tests passed | 50% |
| **Speed** | **Human** time from opening the level to the first passing submission | 25% |
| **Functional** | How much work the **code** does, versus the reference | 25% |

**Speed is the player's solve time. It is not the runtime of their program.**
Runtime efficiency is Functional's job. Conflating them scores one property
twice.

Before changing any weight, curve or threshold, read
[`docs/SCORING.md`](docs/SCORING.md) in full. Every number there was chosen for
a reason that is written down, and the reasons are more load-bearing than the
numbers.

---

## 5. Scars — read before touching the adjacent code

Real bugs, found by running the system rather than reading it. Full write-ups in
[S001](journal/2026-08-08-S001-core-loop.md).

- **M1 — free points on an unmeasurable axis.** Scoring a file from disk reused
  the interactive clock, so a naive O(n·m) solution scored 95.8 and three stars
  on 40 ms of elapsed time. Practice mode now drops Speed, renormalises the
  other two, and does not bank the run. **Lesson: test a scoring system with a
  bad solution, not just a good one.**
- **M2 — a normalisation that saturated.** Pattern shares were
  `min(1.0, count / files)`, so four separate patterns pinned to exactly 100%
  and carried no signal. **Lesson: check the output distribution, not just the
  range.**
- **Q6 — op counts are not comparable across levels.** References span 76 ops
  (`w2-l3-wordfreq`, delegating to `re` and `Counter`) to 5,958
  (`w2-l2-window`, pure Python). Only visible once all six were measured side by
  side. **Lesson: measure the set, not the instance.**

---

## 6. Architecture rules

Full map in [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

- **`runner.run_code` is the seam.** A container-backed runner replaces its body
  in T2. Nothing above `runner.py` should need to change — keep the signature
  stable and resist leaking execution details upward.
- **`models.py` depends on nothing.** Keep it that way.
- **Nothing imports `cli.py`.**
- **Two-pass execution is deliberate.** Untraced for timing and memory, traced
  for op counting, because `sys.settrace` roughly doubles runtime. Do not
  "optimise" this into one pass.
- **The trace format is load-bearing.** `replay.py` consumes it today and T3's
  live engine will consume the same shape. Changing it is a cross-trajectory
  decision, not a local one.

---

## 7. Adding a level

One file in `vibecoder/levels/`, auto-discovered. Full guide in
[`docs/LEVEL_AUTHORING.md`](docs/LEVEL_AUTHORING.md). The contract, enforced
automatically by `tests/test_levels.py`:

- The **starter must fail** its own tests. A starter that passes hands out free
  stars.
- The **reference must pass** every variant, and must satisfy the level's own
  declared style goals.
- A seed reproduces its variant exactly; different seeds produce different data.
- At least four test cases, including hand-written edge cases — randomness will
  not reliably produce the empty list, the boundary value, or the `None`.
- At least one variant large enough that an inefficient solution actually costs
  something. A 12-element input cannot distinguish O(n) from O(n²).
- Test data must be JSON-serialisable; it crosses a process boundary.

Then **play it**. Contract tests prove well-formedness, not quality.

---

## 8. The record system

Forward planning in [`docs/trajectories/`](docs/trajectories/), backward record
in [`journal/`](journal/), both mirrored as JSON in [`data/`](data/).
`tests/test_records.py` enforces the whole thing — schema validity,
journal↔data pairing, contiguous session ids, baseline reproduction, and
resolution of every relative Markdown link in the repository.

### When to write a journal entry

Write one when the session **produced or changed something a future session
needs to know about**: shipped a waypoint, found a bug worth remembering, made a
decision with alternatives, or hit a blocker. Answering a question or reading
code does not need one.

Copy [`journal/TEMPLATE.md`](journal/TEMPLATE.md), fill **every** field, and
write the matching JSON in `data/sessions/`. Both, or neither — the test suite
will catch a lone one.

Rules that matter more than the format:

- **Objectives are observable outcomes**, never activities. "The Functional axis
  separates naive from optimal" — not "work on scoring".
- **Every claim needs evidence**: a command that was run and what it showed. A
  claim you did not verify is marked `UNVERIFIED` and stays that way. Do not
  quietly omit it.
- **Misconceptions are the highest-value field.** What you believed, what
  revealed otherwise, what you now understand, and what it cost. Write these
  even — especially — when the mistake was avoidable.
- **`none` is a valid answer. Blank is not.** A field left empty reads as an
  omission; a field saying `none` is information.
- **The handoff block is written for someone with no memory of this session.**

### Landing a trajectory

Only when every exit criterion has evidence. Update its status, update the
flight board in [`docs/trajectories/README.md`](docs/trajectories/README.md),
write the journal entry citing evidence per criterion, and add a fresh baseline
to `data/baselines/` if measurements changed.

One trajectory holds `IN FLIGHT` at a time. A second one starting means the
first slipped — record that rather than absorbing it silently.

---

## 9. Definition of done

A change is done when **all** of these hold. Report against this list, not a
feeling.

1. Both gates pass (`unittest discover`, `cli verify`).
2. New behaviour has a test, including its failure mode. A test that only covers
   the happy path has not tested anything.
3. Public functions and non-obvious decisions carry docstrings explaining
   **why**, matching the density of the surrounding code.
4. Docs updated if behaviour changed — `SCORING.md` for scoring,
   `ARCHITECTURE.md` for structure, `GLOSSARY.md` for new terms.
5. Journal entry and data twin written, if §8 says one is warranted.
6. Counts and figures quoted in docs still match reality. If the test count
   changed, `grep` for the old number and fix every occurrence.

---

## 10. Anti-patterns specific to this repository

- **Reporting success without running the gates.** The suite takes four seconds.
- **Testing a scorer only with correct solutions.** See M1.
- **Adding a dependency because it would be convenient.** See N1.
- **Describing the sandbox as secure.** See N4.
- **Editing an exit criterion after the fact** so the trajectory looks clean.
- **Writing a journal entry that only records successes.** An entry with an
  empty misconceptions field, after a session that involved real work, is
  usually an incomplete entry rather than a flawless session.
- **Optimising the two-pass runner into one pass.** It corrupts the timing.
- **Making `_harness.py` import from the package** because it would be tidier.
- **Silently narrowing scope to hit a date.** Move the date and say so — the
  slip policy in [`SCHEDULE.md`](SCHEDULE.md) exists for exactly this.

---

## 11. Git

- Develop on the branch the session specifies; create it from the default branch
  if it does not exist.
- Commit messages: what changed and **why**, wrapped at 72 characters. Reference
  the trajectory and waypoint (`T2 W1`) where one applies.
- Never commit player state — `.vibecoder/`, `profile.json`, `runs/` are
  gitignored because run artifacts contain code someone wrote privately.
- Do not open a pull request unless asked.
- `git push -u origin <branch>`; retry network failures with backoff.

---

## 12. Judgement calls

**Decide yourself, mention it, move on:** naming, test structure, refactors
inside a module, which edge cases a level needs, doc wording, where a helper
belongs.

**Ask first:** anything that breaks a non-negotiable, changes a scoring weight
or curve, alters the trace format, changes what is stored about a player, or
moves a trajectory's exit criteria.

**Say it plainly rather than working around it:** if a request conflicts with an
invariant, if the design document is wrong about something, or if a measurement
disagrees with what the docs claim. A disagreement backed by a command you ran
is the most useful thing you can offer here — the two best findings in this
project so far both came from running something adversarially and reporting what
actually happened.
