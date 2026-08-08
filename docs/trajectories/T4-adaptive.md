# T4 — Adaptive difficulty

**Design phase:** 3 · **Status:** `PLOTTED` · **Target:** 2026-10-04 ·
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
edge-case density, and whether a style goal is required. Level `w1-l2-groupby`
at low mastery generates 20 clean rows; at high mastery it generates 300 rows,
30% of them `None`. This reuses the seeded-variant machinery T1 already ships,
which is the main reason variants were built that way.

A decay term matters too: mastery drifts back toward the middle over weeks, so
returning players get re-assessed instead of being permanently pinned to a
rating they earned in August.

## Waypoints

| ID | Waypoint | Notes |
| --- | --- | --- |
| W1 | Persist a per-tag mastery vector in the session profile | Alongside the Vibe Vector, not merged with it — one is measured, one is declared. |
| W2 | Difficulty parameters on `make_tests(rng, difficulty)` | Level authors opt in; the signature stays backwards-compatible. |
| W3 | Update rule above, applied after every ranked run | Practice runs must not move mastery. |
| W4 | Selection policy targeting the ~70–80% success band | Too easy is boring, too hard drives quits. |
| W5 | Drill injection: repeated short exercises on the weakest tag | The design's "struggle with recursion → extra recursive drills". |
| W6 | Time decay on mastery | Re-assess returning players. |
| W7 | Explanation surface: `vibecoder status --why` | The player can see why they were given a level. Non-negotiable. |

## Exit criteria

1. Two players with opposite profiles receive measurably different variant
   parameters on the same level id.
2. Mastery for a tag rises after clears and falls after failures, monotonically
   in the absence of contrary evidence.
3. Success rate across a simulated 50-level run stays inside 60–90%.
4. Every difficulty decision is explainable in one sentence generated from the
   model, with no hidden state.
5. Practice-mode runs provably do not affect mastery.

## Known hazards

- **A death spiral in either direction.** Ratchet difficulty up too eagerly and
  a good player never gets a win; ratchet down too eagerly and a struggling
  player is patronised. Bound the per-level step change.
- **Tag sparsity.** With ~8 tags and 6 levels, some tags will have one data
  point. Require a minimum observation count before a mastery estimate is
  allowed to drive selection; fall back to the Vibe Vector until then.
- **Confusing "what you write" with "what you are good at".** The Vibe Vector
  measures habits; mastery measures performance. A player who uses `pandas`
  constantly may still be bad at it. Keep the two separate — merging them is the
  most tempting and most wrong simplification available here.
- **Unexplainable adaptation feels broken, not smart.** Hence W7.

## Instrument checks

- Simulated players (always-correct, always-naive, improving, plateaued) run
  against the policy; assert the success band holds for each.
- Per-tag mastery trajectories plotted over a session; look for oscillation.
- The honest test: when the game says "you struggle with recursion", does the
  score history actually support that claim?
