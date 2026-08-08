# Glossary

Terms used precisely throughout this repository. Where a word has a loose
everyday meaning and a specific meaning here, the specific one wins.

### Accuracy
Scoring axis: the fraction of hidden tests a submission passes. Weighted 50% on
levels, 40% on boss fights. A fatal run scores zero.

### Baseline
An immutable set of measurements taken at a point in time, stored in
`data/baselines/`. Never edited — a new measurement is a new file. This is what
makes a regression visible instead of arguable.

### Boss fight
The multi-step challenge closing each world, run in slow motion with the player
able to intervene mid-execution. Designed and scheduled ([T3](trajectories/T3-boss-engine.md));
not yet built.

### Competency band
Bloom-style classification of a working session's dominant activity — `Recall`,
`Understand`, `Apply`, `Analyse`, `Evaluate`, `Create`. Recorded in every
journal entry so that a project spending every session at `Apply` becomes
visible as executing rather than designing.

### Elegance bonus
+5% for satisfying every style goal a level declares. One of three bonuses; the
others are `first_try` (+10%) and `clean_first_run` (+5%).

### Exit criteria
Observable facts that make a trajectory done. Written **before** work starts and
never edited to match what was built — if they turn out wrong, that is a finding
for the journal, not a document to quietly amend.

### Functional (axis)
Scoring axis measuring how much work the submitted code does, relative to the
level's reference solution: 70% op count, 30% peak memory, each capped at
parity. Weighted 25% on levels, 30% on boss fights.

### Handoff
The four-field block ending every journal entry — state, next action, blockers,
context required — written so that resuming work does not require re-deriving
the state of the world.

### Isolation boundary
What Phase 0's sandbox provides: protection from a learner's own mistakes
(infinite loops, memory exhaustion, `sys.exit`). Explicitly **not** a security
boundary. See *Security boundary*.

### Level
One playable puzzle: a brief, a starter template, a hidden test generator, and a
reference solution. One file in `vibecoder/levels/`, auto-discovered.

### Mastery
Per-tag performance estimate in [T4](trajectories/T4-adaptive.md), updated from
observed results. **Distinct from the Vibe Vector**, which describes habits.
Someone can use `pandas` constantly and still be bad at it — merging the two is
the most tempting and most wrong simplification available.

### Misconception
A journal field recording what was believed at a session's start that turned out
wrong, what revealed it, and the corrected understanding. The highest-value
field in the rubric.

### Op / op count
A line execution **inside the submitted file**, counted via `sys.settrace` with
events filtered by code filename. A `sorted()` call costs one op; a hand-written
sort costs hundreds. A deterministic efficiency proxy, not a complexity
measurement — and not comparable across levels (see open question Q6).

### Par time
How long a competent player should need on a level. The Speed axis gives full
marks at or under par.

### Practice mode
Scoring a file from disk with no measured solve time. Drops the Speed axis,
renormalises the other two, and does not bank the result. Exists because a
scored axis that cannot be measured honestly is an exploit — see
[M1 in S001](../journal/2026-08-08-S001-core-loop.md).

### Ranked run
A run with an honest solve time, scored on all three axes and banked to the
profile. The opposite of a practice run.

### Reference solution
The solution a level's submissions are benchmarked against on the Functional
axis. A difficulty dial, not an afterthought: it must pass every variant and
satisfy the level's own style goals.

### Security boundary
What Phase 0 does **not** have. Defending against deliberately hostile code
requires container-backed execution, which is [T2](trajectories/T2-sandbox.md)
and gates every multiplayer feature in [T5](trajectories/T5-community.md).

### Seed
The integer that generates a level variant. `level.tests_for(seed)` is
deterministic: the same seed always produces the same puzzle, a different seed
produces a new one of the same shape.

### Session (journal)
One working session, reviewed in `journal/YYYY-MM-DD-Snnn-slug.md` with a
machine-readable twin in `data/sessions/`. Not to be confused with *Session*
(the class), which holds player progression.

### Speed (axis)
Scoring axis measuring **human** time from opening a level to the first
fully-passing submission, against par. Not the runtime of the submitted code —
that is Functional. The single most commonly confused pair of terms here.

### Star
Level rating from the total score: 60 → ★, 80 → ★★, 95 → ★★★. Current thresholds
are guesses pending play data (Q3).

### Style goal
An optional constraint a level declares (`uses_comprehension`,
`uses_recursion`, …) that earns the elegance bonus. Checked against the target
function only, so a helper cannot satisfy one by accident.

### Tag
A content label (`data`, `web`, `algorithms`, `functional`, …) attached to both
levels and Vibe Vectors. The only part of the profile that level recommendation
reads.

### Trajectory
This project's unit of forward planning, replacing "roadmap": a heading with
waypoints and exit criteria. The destination is committed; the path between
waypoints is expected to bend. Statuses: `LANDED`, `IN FLIGHT`, `CLEARED`,
`PLOTTED`, `HOLDING`.

### Variant
One instance of a level, generated from a seed. Replaying a level serves a new
variant — same shape, different data.

### Vibe Tip
Post-level coaching from a rule matching a narrow syntactic shape. Deliberately
conservative: a tip that fires on good code costs the player's trust in every
later tip, so idiomatic code is asserted to produce zero tips.

### Vibe Vector
The statistical fingerprint of a codebase produced by the profiler — libraries,
patterns, naming, complexity, exceptions handled, derived tags. Describes
**habits**, not ability.

### Waypoint
An individually shippable milestone within a trajectory. A waypoint that cannot
ship alone is not a waypoint — it needs splitting.

### World
A themed group of levels ("Data Wrangler", "Algorithm Architect"). Later worlds
carry a higher score multiplier (`1.0 + 0.1 × (world − 1)`).
