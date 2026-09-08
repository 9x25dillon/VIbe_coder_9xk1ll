# T4 — Adaptive difficulty

**Design phase:** 3 · **Status:** `IN FLIGHT` · **Target:** 2026-10-04 ·
**Started:** 2026-09-08 ·
**Depends on:** T1 (score history), T3 (boss telemetry)

## Heading

The Vibe Vector personalises content *once*, from a snapshot of the player's
codebase. T4 closes the loop: the game should keep watching how the player
actually performs and move the difficulty to match — harder data levels for
someone who aced the last one, extra recursion drills for someone who keeps
failing recursion.

The design calls this "machine-learning based on user performance". That
framing is worth pushing back on. With a handful of levels and one player, there
is no training set; a model would be fitting noise and would be impossible to
debug when it made a bad call. **The right first system is an explicit,
inspectable competency model**, and it should be built and measured before
anything is learned statistically.

## The model

Track a per-tag mastery estimate rather than a single global skill number,
because "good at Python" is not a thing the game can act on, while "solid on
comprehensions, weak on recursion" is.

```
mastery[tag] ∈ [0, 1]     one estimate per content tag
```

Updated after each level with an exponentially-weighted move toward the
observed result, so recent evidence dominates without a single bad run erasing
history:

```
observed  = 0.5·(accuracy/100) + 0.3·(functional/100) + 0.2·first_try
mastery  ← mastery + α · (observed − mastery)        α ≈ 0.3
```

Difficulty then selects variant parameters, not different problems: input size,
edge-case density, and whether a style goal is required. Level `w2-l2-groupby`
at low mastery generates 20 clean rows; at high mastery it generates 300 rows,
30% of them `None`. This reuses the seeded-variant machinery T1 already ships,
which is the main reason variants were built that way.

A decay term matters too: mastery drifts back toward the middle over weeks, so
returning players get re-assessed instead of being permanently pinned to a
rating they earned in August.

## Classes, attributes and abilities

Folded in here rather than opened as a trajectory of its own, because the
thing that makes them work already lives in T4: this is the only trajectory
that models a player over time.

The design has three layers and **the split between them is load-bearing**,
for exactly the reason the third hazard below already gives. Merging them is
the tempting and wrong simplification, and it is available here twice over.

| Layer | Derived from | What it is | What it must never be |
| --- | --- | --- | --- |
| **Function class** | The Vibe Vector — *how you write* | An identity. "You reach for comprehensions and delegate to the stdlib." | A rating. A class is never better than another class |
| **Attributes** | Per-tag mastery — *what you are good at* | A measurement, already the model above | Flavour text. An attribute the player cannot see the evidence for is a horoscope |
| **Abilities** | Earned by performance, flavoured by class | Things that spend or refill a fight's resources | Free. An ability that costs nothing is a difficulty setting wearing a costume |

**Classes come from habits, attributes from performance, and the two are not
averaged together.** A player who writes `pandas` constantly is not thereby
good at it — the hazard list says so already, and a class system is the most
attractive way anyone will ever find to violate it. The class says what your
code looks like. The attributes say what it scores. A screen that shows both
is honest; a single number blending them is not.

Abilities have somewhere concrete to act because [T3](T3-boss-engine.md) W6
built one: a boss fight now has **hit points and a bounded repair pool**, and
a repair both reduces the damage its step deals and hands the boss back an
amount scaled by how wrong the code was. That is a resource with a cost curve
already attached, which is what an ability can meaningfully modify — refill a
repair, soften a heal, bank unspent repairs into damage. Designing abilities
before that existed would have been designing against nothing, which is why
this waited for W6 rather than being started when it was first raised.

## Waypoints

| ID | Waypoint | Notes |
| --- | --- | --- |
| W1 | Persist a per-tag mastery vector in the session profile | `LANDED` (S027). Alongside the Vibe Vector, not merged with it — one is measured, one is declared. Lives in [`mastery.py`](../../vibecoder/mastery.py), which imports nothing. |
| W2 | Difficulty parameters on `make_tests(rng, difficulty)` | `LANDED` (S027). Authors opt in one at a time; detection is by signature. **The default reproduces pre-difficulty data byte for byte**, which is what keeps `data/baselines/` evidence. `w2-l2-groupby` is the first to opt in. |
| W3 | Update rule above, applied after every ranked run | `LANDED` (S027). Applied inside `Session.submit`, which practice mode never calls — so criterion 5 holds structurally rather than by a flag. |
| W4 | Selection policy targeting the ~70–80% success band | `LANDED` (S028). Measured at **72%** for an improving player and **71%** for a plateaued one, pooled over 20 simulated 50-level runs. Two of the four simulated players **cannot** be held in the band by any policy built on W2's dial — see below. |
| W5 | Drill injection: repeated short exercises on the weakest tag | The design's "struggle with recursion → extra recursive drills". |
| W6 | Time decay on mastery | Re-assess returning players. |
| W7 | Explanation surface: `vibecoder status --why` | The player can see why they were given a level. Non-negotiable. |
| W8 | Derive a **function class** from the Vibe Vector, with the evidence attached | Named from habits, never from score. `status` shows which patterns earned it. |
| W9 | Surface **attributes** as the per-tag mastery vector already measured, in the same view | No new model — W1's numbers, made legible. The evidence rule from W7 applies unchanged. |
| W10 | **Abilities** that act on a boss fight's resources (T3 W6's HP and repair pool) | Each has a cost. An ability with no cost is a difficulty setting in a costume. |
| W11 | Earning and equipping: which abilities a class unlocks, and at what mastery | The only place the two layers are allowed to meet, and they meet as a *gate*, never as an average. |

## What W4 measured, and what it could not

Exit criterion 3 asks that a simulated 50-level run stay inside 60–90%, and
the instrument check asks for that band to hold for all four named players.
Measured over 20 seeds × 50 runs each:

| Simulated player | Success | In band |
| --- | --- | --- |
| Improving | 72% | ✅ 40/40 seeds |
| Plateaued | 71% | ✅ 38/40 seeds |
| Always-correct | **100%** | ❌ 0/40 |
| Always-naive | **100%** | ❌ 0/40 |

**The last two cannot be fixed by any selection policy**, and the reason is
structural rather than a tuning failure. W2's difficulty scales *how much work
an input demands*, not whether the answer is right — that is the design, and
it is why a level's hand-written edge cases survive every difficulty. A player
who always writes a correct solution therefore always clears, at every
difficulty, and no dial reaches them. "Always-naive" in this codebase means
O(n²) and **right** (M1 in [S001](../../journal/2026-08-08-S001-core-loop.md),
where a naive solution scored 95.8), so it lands in the same place.

The policy is not idle for them. A low Functional score drags the naive
player's mastery down and they settle at a gentler variant (0.61) than the ace
(0.90) — but being correct first time weighs 0.7 of the observation, so
mastery cannot fall below that floor however inefficient the code is.

Criterion 3 stands as written; N7 forbids re-cutting it to match what was
built. **Q89** carries the finding: either "success" means something other
than "cleared" for a scored game, or the criterion needs a player who can
actually fail.

The other measured surprise: **`STRETCH`, the policy's offset, barely moves
the band** — 70% with no offset at all, 74% at three times the shipped value.
The loop is self-correcting, so the equilibrium is set by the *observation
weights* in [`mastery.py`](../../vibecoder/mastery.py), not by the policy's
dial. Anyone trying to move the band should turn those.

## Exit criteria

1. Two players with opposite profiles receive measurably different variant
   parameters on the same level id.
2. Mastery for a tag rises after clears and falls after failures, monotonically
   in the absence of contrary evidence.
3. Success rate across a simulated 50-level run stays inside 60–90%.
4. Every difficulty decision is explainable in one sentence generated from the
   model, with no hidden state.
5. Practice-mode runs provably do not affect mastery.
6. A player's function class is derivable from the Vibe Vector alone, and
   changing their *scores* without changing their *code* never changes it.
7. Every ability has a stated cost, and a fight with abilities available is
   still losable.
8. No screen anywhere presents a single number blending habits with mastery.

Criteria 6–8 were added when classes, attributes and abilities were folded in
(see [S021](../../journal/2026-09-06-S021-boss-hp.md)). They are new scope with
new criteria, not the existing five re-cut to fit something already built —
1–5 are untouched.

## Known hazards

- **A death spiral in either direction.** Ratchet difficulty up too eagerly and
  a good player never gets a win; ratchet down too eagerly and a struggling
  player is patronised. Bound the per-level step change.
- **Tag sparsity.** With ~10 tags and 12 levels, some tags will have one data
  point. Require a minimum observation count before a mastery estimate is
  allowed to drive selection; fall back to the Vibe Vector until then.
- **Confusing "what you write" with "what you are good at".** The Vibe Vector
  measures habits; mastery measures performance. A player who uses `pandas`
  constantly may still be bad at it. Keep the two separate — merging them is the
  most tempting and most wrong simplification available here.
- **Unexplainable adaptation feels broken, not smart.** Hence W7.
- **Power creep dissolves the boss engine.** T3 W6 made a fight cost
  something; an ability that refills repairs freely gives that back and
  returns the boss to the pre-W6 state where fixing was unlimited. Every
  ability needs a cost, and the instrument check is whether a fight with a
  full ability loadout can still be lost.
- **A class system is a horoscope by default.** "You are a Comprehensionist"
  is flattery unless the patterns that earned it are on screen next to it.
  W8's evidence requirement is not decoration; it is the difference between a
  measurement and a personality quiz.

## Instrument checks

- Simulated players (always-correct, always-naive, improving, plateaued) run
  against the policy; assert the success band holds for each.
- Per-tag mastery trajectories plotted over a session; look for oscillation.
- The honest test: when the game says "you struggle with recursion", does the
  score history actually support that claim?
