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
| W5 | Drill injection: repeated short exercises on the weakest tag | `LANDED` (S029). Three runs on the weakest **confident** tag below 0.5, injected after a clear and shown in `status` rather than hidden behind a command nobody runs. |
| W6 | Time decay on mastery | `LANDED` (S030). A three-week half-life on **both** the value and the observation count, applied as a view at read time. Eroding confidence is what makes a returning player *unmeasured* rather than *weak* — and is the answer to Q90. |
| W7 | Explanation surface: `vibecoder status --why` | `LANDED` (S031). Shows what was measured, what the game would give them for every level, and **what the model does not know** — the last generated from the content rather than written down. |
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

## Drills (W5)

A drill is `DRILL_LENGTH` runs on the one tag the player is measurably weakest
at. Three constraints shape it, and each rules something out:

- **Only a confident tag.** Drilling a tag measured once acts on a single
  unlucky afternoon, which is what `MIN_OBSERVATIONS` exists to prevent. A
  player who has never met a tag needs to meet it — that is the selection
  ordering's job, not a drill's.
- **Only below 0.5.** A drill offered to someone who does not need one is
  noise, and it teaches them to ignore the next one.
- **`DRILL_LENGTH` is `MIN_OBSERVATIONS`, not a round number.** After a drill
  the tag is `confident` again by definition, so the game is never adapting to
  a drill whose result it cannot yet measure.

It is *injected* rather than offered: the moment after a clear is when the
game has the player's attention and is being asked "what now", so that is
where it appears, with campaign order still shown beneath it. A separate
`vibecoder drill` command would have been a thing nobody runs.

Where a tag is carried by several levels the queue cycles them, because asking
the same question three times drills the level rather than the skill. Where it
is carried by one — `recursion`, `regex`, `numeric` — it repeats that level,
and the evidence reports `distinct_levels: 1` so the thinness is visible
rather than implied.

## Drills (W5)

A drill is `DRILL_LENGTH` runs on the one tag the player is measurably weakest
at. Three constraints shape it, and each rules something out:

- **Only a confident tag.** Drilling a tag measured once acts on a single
  unlucky afternoon, which is what `MIN_OBSERVATIONS` exists to prevent. A
  player who has never met a tag needs to meet it — that is the selection
  ordering's job, not a drill's.
- **Only below 0.5.** A drill offered to someone who does not need one is
  noise, and it teaches them to ignore the next one.
- **`DRILL_LENGTH` is `MIN_OBSERVATIONS`, not a round number.** After a drill
  the tag is `confident` again by definition, so the game is never adapting to
  a drill whose result it cannot yet measure.

It is *injected* rather than offered: the moment after a clear is when the
game has the player's attention and is being asked "what now", so that is
where it appears, with campaign order still shown beneath it. A separate
`vibecoder drill` command would have been a thing nobody runs.

Where a tag is carried by several levels the queue cycles them, because asking
the same question three times drills the level rather than the skill. Where it
is carried by one — `recursion`, `regex`, `numeric` — it repeats that level,
and the evidence reports `distinct_levels: 1` so the thinness is visible
rather than implied.

## Decay (W6)

An estimate loses half its force every `HALF_LIFE_DAYS` (21). Two things decay
together, and the second is the one that matters.

The **value** drifts toward `UNSEEN` — toward the middle, in whichever
direction it sits, because age makes a rating *unknown* rather than *bad*. The
**observation count** erodes with it, so a stale estimate stops being
`confident` and the game falls back to asking instead of assuming.

| Away | Value (from 0.9) | Observations (from 6) | Confident |
| --- | --- | --- | --- |
| same day | 0.90 | 6 | yes |
| 1 week | 0.82 | 4 | yes |
| 3 weeks | 0.70 | 3 | yes |
| 6 weeks | 0.60 | 1 | **no** |
| 4 months | 0.51 | 0 | no |

**Decaying only the value would have been the bug.** A returning player would
read as *measured and mediocre* rather than *unmeasured*, and those want
opposite responses: one is a reason to drill them, the other a reason to
re-assess them. That is **Q90**, answered by construction rather than by a
rule — confidence is already this model's vocabulary for "we do not know yet",
so staleness is expressed in it instead of in a second mechanism.

Decay is a **view**, applied by `Mastery.as_of(now)` at one call site
(`Session.current_mastery`). The stored profile stays a record of what was
actually measured rather than one that rots on disk; only `observe` writes
decay back, and only because a new run has genuinely superseded the old
reading.

## The explanation surface (W7)

`vibecoder status --why` has four parts, and the fourth is the one the
waypoint calls non-negotiable:

1. **What has been measured** — every tag with evidence, weakest first, each
   showing its run count and whether it is enough to act on. A tag the game
   has a number for and is *ignoring* is shown as such; hiding it would make
   the drill's choice look arbitrary.
2. **What you would be given right now** — every level, its band, and the
   sentence behind it.
3. **The drill**, if one is warranted.
4. **What this does not know.**

**Nothing on the screen is computed for display.** Every sentence is the
`reason` the decision was actually made with, so the screen cannot drift from
the behaviour — which is what exit criterion 4's "no hidden state" amounts to
in practice, as opposed to a second rendering that happens to agree today.

### Saying what the model is not claiming

`policy.limits` generates the caveats **from the content**, so a level gaining
a tag changes what the player is told without anyone remembering to edit a
paragraph. Two are real properties of the model rather than modesty:

- *a level's tags all move together, so a score for `data` is about the levels
  that carry it rather than that skill on its own* — **Q87**
- *`recursion` is carried by a single level, so the score measures that level
  as much as the skill* — **Q88**, stated at the right strength: thin, not
  unusable.

**Q91 is fixed here too.** A returning player whose evidence has decayed used
to be told "nothing measured yet" — true of the decayed model and false about
their history. There is now a `stale` source: *you have played data before,
but not recently enough for the reading to still count*. The decision is the
same standard variant; only the sentence is honest.

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
