# Hand-off — 2026-09-10

Read this first, then [CLAUDE.md](CLAUDE.md). This file describes the current
state; historical session accounts live in [journal/](journal/README.md).

## Start here

VibeCoder now has a shared terminal cockpit. The user authorized implementing
the visual overhaul and then committing, rebasing, pushing, opening a PR, and
merging it. The delivery branch is `feat/terminal-cockpit`, targeting `main`.
Check the actual GitHub merge state rather than inferring it from this file:

```bash
git status --short
git branch --show-current
git log -5 --oneline
gh pr list --state all --head feat/terminal-cockpit
```

The prior delivery authorization applies to this overhaul; it is not blanket
authorization to merge unrelated future work. No player data belongs in Git.

**Use Python 3.11 on this machine.** `python3` resolves to 3.14. The project
metadata still declares Python 3.10+; this session did not establish 3.14
compatibility. Read the existing runtime notes before expanding support.

Open the game in a real terminal:

```bash
python3.11 -m vibecoder.cli levels --browse
```

For exploratory runs that could save progress, set `VIBECODER_HOME` to a new
scratch directory first. Do not overwrite the player's actual profile.

## What changed

| Area | Behavior | Main files |
| --- | --- | --- |
| Shared presentation | Cyan focus, neutral chrome, semantic status colors; bounded text regions and scrollable inspectors | [cockpit.py](vibecoder/cockpit.py), [ui.py](vibecoder/ui.py) |
| Campaign | Arrows select; Enter launches a level or live boss; returning from the challenge reopens the browser | [campaign.py](vibecoder/campaign.py), [cli.py](vibecoder/cli.py) |
| Editor | Objective sidebar from 110 columns; full-width objective/help views; persistent verdict, failure, advice, and score; horizontal source scrolling | [editor.py](vibecoder/editor.py) |
| Boss | Interpreter-driven machine view with HP, repairs, and encounter progress; live event count does not imply a known total | [encounter.py](vibecoder/encounter.py), [vision.py](vibecoder/vision.py) |
| Repair | Error, authored objective, local values, and resources remain inspectable; controls stay visible during errors | [repair.py](vibecoder/repair.py) |
| Results and map | Verdict and total precede detailed axes; text map names every level and exposes launch commands | [cli.py](vibecoder/cli.py), [ui.py](vibecoder/ui.py) |

Controls: `ctrl-o` opens objective/details, `ctrl-g` opens editor help, `ctrl-p`
toggles editor rhythm, `ctrl-r` runs/resumes, and `ctrl-x` quits. Arrow keys and
PgUp/PgDn scroll open inspectors; Escape returns to code. During live boss
animation, `q` stops the fight. Minimum terminal size remains 48 × 12.

See [the UI guide](docs/UI.md), [architecture](docs/ARCHITECTURE.md),
[rendered preview](docs/visual-overhaul.svg), and
[today's work review](docs/reviews/2026-09-10.md).
Regenerate the illustrative SVG with `python3.11 tools/preview_ui.py`.
The preview's dark background is not imposed on the user's terminal.

## Evidence and how to verify

The implementation passed **1420 tests** in an unpinned full run and **54/54**
reference runs. The final publication checks are recorded in S039. The new
[test_cockpit.py](tests/test_cockpit.py) contains 24 interaction/layout checks.

```bash
python3.11 -m unittest discover -s tests -p 'test_cockpit.py'
python3.11 -m unittest discover -s tests
python3.11 -m vibecoder.cli verify --seeds 3
python3.11 -m vibecoder.cli showcase | cat
python3.11 -m vibecoder.cli levels --map | cat
```

- Both piped commands were checked for zero escape bytes.
- Real PTY smoke checks covered campaign → objective → passing submission →
  campaign, repair inspect → resume, and a live boss reference fight. Terminal
  settings were restored. The temporary driver was
  `/tmp/vibecoder-pty-smoke.py`; it is **not a durable repository test** and may
  be absent next session. The committed tests cover the pure frames and selected
  lifecycle contracts, not the entire PTY workflow.
- Full isolation tests need access to the host's bubblewrap/Docker backends.
  Restricted execution made those unavailable and changed discovered counts;
  it was not evidence of a game regression. Use the normal permission mechanism
  for the full gate. Do not weaken sandbox assertions to obtain a green run.
- The full gate took about a minute in this session. Backend availability and
  container startup affect duration and discovery counts; avoid treating past
  timings or pinned counts as constants.

## First useful task next session

Human-playtest the visual overhaul at **80 × 24** and **120 × 30**. This remains
unverified despite automated PTY coverage. Exercise a failing level, read the
full error and hint, fix it, return to the campaign, and enter a boss repair.
Record a few concrete observations before changing layout or pacing.

If it feels good, return to the community roadmap: **T5 W3**, score submission
with server-side re-verification. Read
[T5's hazards](docs/trajectories/T5-community.md) before designing a server.
T1, T3, T4, T6, and T7 remain landed. T5 W1/W2 are complete; T2 W4 remains
blocked on a registered OAuth application.

## Decisions and invariants to preserve

- **Q100 is still undecided:** server-side verification cannot establish human
  solve time. The proposed leaderboard uses Accuracy + Functional and treats
  Speed as personal information. That changes scoring semantics and requires
  explicit user approval. This overhaul's merge authorization does not answer it.
- Q84, bosses' role in progression, and Q89, the success-band instrument check,
  remain existing product questions. Q101 asks how the new UI feels in sustained
  human play.
- No third-party dependencies. Scoring weights, repair costs, persistence
  formats, and trace shapes did not change in this overhaul.
- Color is decoration; layout remains readable at every color depth. Preserve
  ASCII, `NO_COLOR`, and reduced-motion behavior. Reduced-motion and piped live
  fights retain transcripts.
- `TerminalSession.resized` is a **consuming boolean property**, not a method.
  The real terminal smoke test exposed the mistake; the relevant callers and
  regression test were corrected. Do not copy an old `.resized()` call.
- Restore terminal ownership before launching another screen. Browser,
  challenge, encounter, and repair sessions must not nest alternate screens.
- Inspectors use authored briefs; do not expose hidden tests as examples.
  A presentation label such as “Solve time” does not authorize changing Speed.
- `_harness.py` never imports the package. The profiler never executes analyzed
  source. Untrusted submissions must retain their provenance and isolation.
- Community level loading is not secured just by sandboxing reference runs:
  Python module imports and `make_tests` currently run in the parent. T5 sharing
  needs an appropriate data format before accepting third-party levels.
- Committed `data/` records are immutable. Add a superseding record rather than
  rewriting history. Keep journal/data twins and living test counts consistent.

## Working efficiently

Read local context before invoking tools. Batch independent reads and tests;
keep writes and dependent Git operations sequential. Run focused checks while
editing, then the full gate before committing. Do the real terminal smoke check
early when changing lifecycle code; pure composition cannot validate it.

Use concise progress updates, with evidence in the final report. Complete the
authorized work without repeated confirmation; ask only for genuinely missing
decisions or required permission. Rewrite this handoff when scope changes:
remove stale relative dates and clearly distinguish measured results from human
validation still needed.
