# Work schedule

Calendar plan from T1 landing to a feature-complete Phase 4. Weeks run Monday
to Sunday. Dates are real and fixed; **scope inside a week is what flexes**, not
the trajectory ordering.

**Baseline:** [T1](docs/trajectories/T1-core-loop.md) landed Saturday
2026-08-08 ([S001](journal/2026-08-08-S001-core-loop.md)).

## Cadence

| Ritual | When | Output |
| --- | --- | --- |
| **Session review** | End of every working session | A [journal](journal/) entry + its [data twin](data/sessions/) |
| **Week close** | Friday | Update the flight board in [docs/trajectories/README.md](docs/trajectories/README.md); carry open questions forward |
| **Baseline refresh** | Whenever a trajectory lands | A new immutable file in [data/baselines/](data/baselines/) |
| **Trajectory landing** | Exit criteria met | Journal entry citing evidence for *each* criterion |

One trajectory holds `IN FLIGHT` at a time. A second one starting means the
first slipped, and that is a fact to record rather than absorb silently.

## Calendar

### Phase 1 — Trusted execution & ingestion · [T2](docs/trajectories/T2-sandbox.md)

| Week | Dates | Waypoints | Deliverable |
| --- | --- | --- | --- |
| **W01** | Mon 10 Aug – Sun 16 Aug | T2 W1, W2 | Container-backed runner behind `run_code`; network off, read-only rootfs, non-root, seccomp |
| **W02** | Mon 17 Aug – Sun 23 Aug | T2 W3, W4 | Untrusted-source flag forcing the container path; GitHub OAuth device flow → shallow clone → profile → discard |
| **W03** | Mon 24 Aug – Sun 30 Aug | T2 W5, W6, W7 | `.zip` ingestion with bomb guards; ingestion budgets; Vibe Vector versioning + migration |

**Gate — Fri 28 Aug:** the adversarial suite (`tests/test_sandbox_escape.py`)
must be green in CI before any ingestion path is enabled for a non-local source.
Ingestion without a real sandbox is the same bug with a wider aperture.

**T2 lands: Sun 30 Aug.**

### Phase 2 — Boss engine · [T3](docs/trajectories/T3-boss-engine.md)

| Week | Dates | Waypoints | Deliverable |
| --- | --- | --- | --- |
| **W04** | Mon 31 Aug – Sun 6 Sep | T3 W1, W2 | Multi-step boss level format; live stepping under `sys.settrace` with pause/resume/abort |
| **W05** | Mon 7 Sep – Sun 13 Sep | T3 W3, W4 | Step-back over recorded history; **edit-and-resume (strategy A)** |
| **W06** | Mon 14 Sep – Sun 20 Sep | T3 W5–W8 | Divergence detector; boss HP; 40/30/30 boss scoring; two boss fights |

**⚠ W05 is the schedule risk.** Edit-and-resume is the only waypoint in the
project whose difficulty is genuinely unknown — CPython will not let you swap
the code object of a running frame, so the feature depends on replay being
deterministic (see the strategy table in T3).

*Contingency:* ship W1–W3 as a playable "watch it run, restart on error" boss
and defer W4 to W07. A slip degrades the feature rather than deleting it, and
the boss fight stays playable either way. **Decide by Wed 9 Sep** — not at the
end of the week, when the decision costs a week instead of two days.

**T3 lands: Sun 20 Sep.**

### Phase 3 — Adaptive difficulty · [T4](docs/trajectories/T4-adaptive.md)

| Week | Dates | Waypoints | Deliverable |
| --- | --- | --- | --- |
| **W07** | Mon 21 Sep – Sun 27 Sep | T4 W1–W4 | Per-tag mastery vector; `make_tests(rng, difficulty)`; update rule; selection policy targeting a 70–80% success band |
| **W08** | Mon 28 Sep – Sun 4 Oct | T4 W5–W7 | Drill injection on the weakest tag; time decay; `status --why` explanation surface |

This is also where the open questions from S001 get settled — Q1 (memory
weighting), Q3 (star thresholds), Q4 and Q6 (reference calibration). All four
need play data, which is why they wait until there is some.

**T4 lands: Sun 4 Oct.**

### Phase 4 — Community · [T5](docs/trajectories/T5-community.md)

| Week | Dates | Waypoints | Deliverable |
| --- | --- | --- | --- |
| **W09** | Mon 5 Oct – Sun 11 Oct | T5 W1–W3 | Deterministic daily seed; local leaderboard; score submission with server-side re-verification |
| **W10** | Mon 12 Oct – Sun 18 Oct | T5 W4–W7 | Vibe-filtered leaderboards; level editor + validation; sharing via container execution; achievements and New Game+ |

**Hard gate:** T5 W6 (level sharing) may not ship unless T2 W1–W3 are landed
and verified. A community level is a stranger's Python executed on a player's
machine.

**T5 lands: Sun 18 Oct.**

## Milestones

| Date | Milestone |
| --- | --- |
| Sat 8 Aug 2026 | ✅ T1 — core loop playable, scored, tested |
| Fri 28 Aug 2026 | Sandbox escape suite green in CI |
| Sun 30 Aug 2026 | T2 — untrusted code contained; GitHub ingestion live |
| Wed 9 Sep 2026 | Go/no-go on edit-and-resume |
| Sun 20 Sep 2026 | T3 — boss fights playable |
| Sun 4 Oct 2026 | T4 — difficulty adapts and explains itself |
| Sun 18 Oct 2026 | T5 — dailies, leaderboards, community levels |

## Working assumptions

Stated so they can be checked rather than assumed.

1. **Roughly one substantial session per week.** Two-week trajectories assume
   two; three-week ones assume three. Fewer means the dates move — the dates
   moving is fine, quietly compressing scope to hit them is not.
2. **Test suite stays green at every commit.** It runs in under 4 seconds; there
   is no excuse.
3. **No third-party dependency enters without a journal entry justifying it.**
   Zero dependencies is a property worth defending, and T2's container runner is
   the first genuinely hard case.
4. **Every trajectory lands with evidence.** Exit criteria are verified by
   something that was run, not by reading the code and agreeing with it.

## Slip policy

When a week does not deliver:

- **Do not** silently move the waypoint into the next week and reprint the plan.
- **Do** record what happened in the session journal, with the friction that
  caused it.
- **Then** either cut scope inside the trajectory, or move the landing date and
  every date after it.

Two consecutive slips on one trajectory means the waypoints were wrong. Re-plot
the trajectory rather than continuing to miss the same estimate — and record
that the estimate, not the effort, was the problem.
