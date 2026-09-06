# The Vibe Profiler

The profiler reads a codebase and produces a **Vibe Vector**: a statistical
fingerprint of how someone writes Python. That vector drives which levels the
game recommends and which coaching tips it considers relevant.

## What it does not do

It never executes the code it analyses. `profiler.py` is pure `ast` walking,
start to finish. Given that its input is other people's repositories — and that
[T2](trajectories/T2-sandbox.md) will point it at GitHub — this is a security
property, not a stylistic preference.

It also never persists source. The Vibe Vector is derived statistics; the code
it came from is discarded. That commitment is written into
[`data/README.md`](../data/README.md) as a rule about what may be stored.

## Running it

```bash
vibecoder profile ~/code/my-project      # human-readable
vibecoder profile ~/code/my-project --json > vibe.json
vibecoder profile ~/Downloads/repo.zip   # an archive, read without unpacking
```

The result is saved into the player's profile and used automatically by
`vibecoder levels`.

## What it extracts

| Signal | How | Used for |
| --- | --- | --- |
| **Libraries** | Top-level module of every import | Content tags — `pandas` → `data`, `flask` → `web` |
| **Patterns** | AST node types: comprehensions, generators, lambdas, decorators, classes, f-strings, `with`, `try`, `map`/`filter`/`reduce`, recursion, type hints | Tags, plus tip relevance |
| **Exceptions handled** | `ExceptHandler` names, including bare `except:` | Which failure modes the player already thinks about |
| **Function length** | `end_lineno − lineno`, averaged | Calibrating level size |
| **Complexity** | Cyclomatic: 1 + branch points, counting each extra `BoolOp` operand and each comprehension `if` | Difficulty calibration |
| **Docstring ratio** | Documented functions ÷ total | Whether documentation goals are worth setting |
| **Naming** | Classifies every stored name and function name | Presentation, and detecting a house style |
| **PEP 8 conventions** | Conformance per identifier *kind*: classes vs `PascalCase`, functions vs `snake_case`, module constants vs `SCREAMING_SNAKE` | Detecting a house style without conflating two conventions |
| **Nesting depth** | Deepest indented block per function, counting an `elif` chain once | Whether somebody returns early or steps right |
| **Comment density** | Comment lines ÷ non-blank lines | How much prose the player writes alongside code |
| **Style signature** | A few readable traits derived from all of the above | The sentence a player actually reads |

### Why conventions are judged per kind

`PascalCase` is correct for a class and wrong for a function, and both are the
same token shape. A single pooled "PascalCase share" cannot tell them apart, so
the profiler originally left class names out of `naming` altogether — which
reported **0% PascalCase for a codebase made of classes** and lost the signal
rather than fixing the conflation. Conventions are now counted per kind, and a
kind the codebase has none of is *absent* rather than reported as 0%: telling
somebody they name every class wrongly when they have written no classes is
worse than saying nothing.

### Why complexity is a distribution

`max_complexity` is one function on a bad day. The profile reports median, p90
and max together, because "usually 3, sometimes 9, once 29" describes a codebase
and a single number describes an outlier.

### Why `elif` chains are flat

An `elif` chain nests in the AST — each branch is an `If` inside the previous
one's `orelse` — and is flat on screen. Counting the AST shape reported this
profiler's own dispatch chain as **22 levels deep** when a reader sees one. What
is being measured is the indentation a person looks at, so the chain counts
once, and a nested function starts its own budget rather than being charged to
the function containing it.

Directories that are obviously not the player's own code (`.venv`,
`node_modules`, `__pycache__`, `build`, `site-packages`, …) are skipped, and
`__future__` is excluded from libraries — it says nothing about what someone
likes to build with.

Files that fail to parse are counted and skipped. A repository with one Python 2
file in it still profiles.

## Versioning, and the direction that actually loses data

The vector has gained fields in three separate sessions and will gain more, so
it carries a `version` and a migration chain. Two directions of failure matter,
and the obvious one was never the dangerous one.

**Backward** — an old profile read by this build — was already survivable by
accident, because every field has a default. A version 1 profile from before
any style or budget field existed still loads; `migrate_vector` walks it
forward one step at a time rather than guessing in one leap.

**Forward** — a profile written by a *newer* build and read by this one — was
silently destructive. `from_json` dropped unknown keys, so an ordinary
`vibecoder status` would load a newer profile, re-save it, and permanently
delete whatever that build had recorded. Nothing reported it.

A migration can only be written by the build that knows what a field means, so
this build cannot migrate a future profile. What it can do is **refuse to
destroy it**: unknown fields are kept verbatim in `unknown` and merged flat
again on save, so a newer build finds its fields exactly where it left them
rather than in a quarantine bucket it would have to know to look in. The
profile also keeps its own higher version number — claiming it as ours would
assert we understand fields we have never heard of, and re-saving would look
like a downgrade rather than the pass-through it is.

```
  [NEWER PROFILE]  written by a newer VibeCoder (schema 6);
                   2 field(s) preserved but not read
```

### The chain

| Version | Added |
| --- | --- |
| 1 | The original vector (S001) |
| 2 | Conventions, the complexity distribution, nesting, comment density (S011) |
| 3 | `partial`, `partial_reason`, `files_seen` (S014) |
| 4 | The version field itself, and preservation of unknown fields (S015) |

A profile with no `version` **is** version 1: the field was added in version 4,
so its absence dates the profile rather than making it unreadable.

Every migration so far is additive — the dataclass defaults already supply the
new fields — but each step is written out rather than left implicit, because a
gap at version *n* is indistinguishable from nobody having thought about *n*.
The test suite checks the chain for gaps, checks no step points past the
current version, and proves the machinery **transforms** correctly using a
synthetic renaming migration. That last one matters: every real step being
additive means the transforming path would otherwise go untested until the
first time a field genuinely moves, at which point a failure would not say
whether the migration or the mechanism was wrong.

Bumping `VECTOR_VERSION` without adding the matching step raises `ValueError`
on load. Failing loudly beats loading a profile whose fields mean something
else.

## Budgets, and what a partial profile is

A codebase can be enormous. `vibecoder profile` bounds what it will spend
before it stops looking, and — this is the whole design — **stopping is not
refusing**. `ProfileBudget` is deliberately a different thing from
`ingest.IngestLimits`, and the difference is the verdict:

| | Decides | On breach |
| --- | --- | --- |
| `IngestLimits` | Is this archive **hostile**? | Refuse it. Nothing is read |
| `ProfileBudget` | Have we looked at **enough**? | Keep what was profiled, flag it partial |

Refusing a monorepo would be the worse failure. 20,000 files is an ample sample
of how somebody writes, and the alternative is telling them their code is too
big to look at.

| Budget | Default | What it bounds |
| --- | --- | --- |
| `max_files` | 20,000 | Files profiled. Four times the repository exit criterion 6 describes |
| `max_total_bytes` | 64 MB | Source analysed. Python's whole standard library is 12 MB |
| `max_seconds` | 60 s | Wall clock across the walk *and* the analysis — the one limit that bounds shapes the others cannot predict: a slow disk, a network mount |
| `max_walk_files` | 200,000 | Paths enumerated, bounding what the file list itself costs |

The defaults are sized from measurement, not taste: a 5,000-file, 6.6 MB
repository profiles in **11.7 s**, so exit criterion 6's repository finishes
comfortably and the budget only bites for something several times larger. They
were *not* sized from the standard library, whose files average 16.6 KB against
a normal repository's 1.3 KB — see M27 in
[S013](../journal/2026-09-06-S013-machine-view.md).

A partial profile **is saved**. It describes real code — a smaller sample, not a
wrong one — and it says so on its face:

```
  files            412 of 5,183
  [PARTIAL]  stopped by file budget: 412 files; 4,771 files not read
```

`partial` means *we stopped looking*, never *something was unusable*. A
repository with one Python 2 file in it is completely profiled; it just has one
file's less signal.

### The walk prunes rather than filters

`iter_python_files` walks with `os.walk` and prunes `SKIP_DIRS` from `dirnames`
**during** traversal. The previous implementation was
`sorted(root.rglob("*.py"))`, which descends into `.git`, `node_modules` and
`.venv` in full and only then discards what it found — on a real repository
that is most of the walk, and the walk is the part that has to not hang. On a
tree of 50 source files beside 20,000 vendored ones, pruning is **551× faster**
(167 ms → 0.3 ms) for an identical result.

Entries are sorted within each directory, so the order is deterministic without
materialising the tree. That matters more than it looks: when a budget truncates
a profile, *which* files were seen must not depend on the order the filesystem
happened to return them, or the same repository would profile differently twice.

Symlinked directories are not followed, so a link loop is not an infinite walk.

## Reading an archive

`vibecoder profile` accepts a `.zip` as well as a directory, which is [T2](trajectories/T2-sandbox.md)
W5. An archive is recognised by content rather than by extension — the
end-of-central-directory record, so a `.whl`, an `.egg` or a download that lost
its suffix all route the same way — and an archive of a checkout profiles
identically to the checkout, because the transport must not change the
measurement.

Two structural properties do most of the safety work, and both hold by
construction rather than by care:

- **Nothing is written to disk.** Members are decompressed into memory, parsed,
  and dropped. There is no extraction directory, so there is no cleanup step
  that can fail — which is how T2's "no source retained afterwards" commitment
  is met. It also makes path traversal unreachable: `../../.ssh/id_rsa` is a
  string we reject, not a file we nearly wrote.
- **Only `.py` members are ever opened.** A nested archive, a 4 GB blob of
  zeros and an ELF binary are all skipped unread, which shrinks the
  decompression surface to Python source.

What remains is a two-stage guard in [`ingest.py`](../vibecoder/ingest.py). The
central directory is judged **before a single byte is decompressed** — a bomb
detected while inflating has already cost what it set out to cost — and then
the bytes that actually arrive are measured against what the directory claimed.

| Limit | Default | What it stops |
| --- | --- | --- |
| `max_archive_bytes` | 200 MB | Work done before any check runs |
| `max_entries` | 50,000 | A million empty members that expand to nothing and still cost a million iterations |
| `max_declared_bytes` | 500 MB | The zip bomb proper, decided from the directory |
| `max_file_bytes` | 4 MB | One enormous member. CPython's largest stdlib module is under 1 MB |
| `max_ratio` | 100:1 | A bomb spread thinly across members, each one individually legal |

There is deliberately **no total size limit here** — that was Q46, and the
answer is that by the streaming stage hostility has already been ruled out:
every signal that an archive is an attack lives in the central directory and was
judged before a byte was decompressed. What is left is an archive that is merely
large, which is the same situation as a large directory, and the honest response
is a partial profile rather than a refusal. `ProfileBudget` owns size for both
transports.

The ratio only applies above `ratio_floor` (1 MB): a 12 KB file that compresses
200:1 is a text file full of spaces, not an attack. Deflate tops out near
1032:1 and source code lands between 2:1 and 5:1, so 100:1 is far outside
anything a codebase reaches by accident.

Rejection fails the **whole archive**, not the offending member. An archive
containing a traversal entry is not a codebase with one odd file in it, and
profiling the remainder would amount to deciding that hostile input is fine as
long as it is handled neatly.

### What the guard turned out not to need

The central-directory checks trust numbers written by whoever built the
archive, so the streaming stage re-measures what arrives. That check has never
fired in practice, and the reason is worth writing down: `zipfile.ZipExtFile`
sets its output budget from the declared `file_size` and then verifies the
directory's CRC against what it inflated, so a member physically cannot expand
past its declaration through that reader, and forging a size costs the forger
that member. The bounded read stays because that is an implementation detail of
one interpreter rather than a documented contract —
`test_a_reader_that_ignores_the_declared_size_is_still_caught` simulates the
reader that does not bound itself.

## Normalisation, and the bug that shaped it

Pattern values are all 0–1 so they compare across codebases of any size. **How**
they are normalised turned out to matter more than expected.

The first implementation used `min(1.0, occurrences / files)`. Self-profiling
reported exactly **100% for four separate patterns**, including `try_except` and
`fstring` — anything appearing more than once per file on average pinned to the
cap. The normalisation had destroyed precisely the signal it existed to expose,
and since saturated patterns cannot discriminate, every downstream tag decision
would have quietly degraded.

The fix splits the two cases:

- **File-level patterns** (comprehension, f-string, class, `try`, lambda, …) →
  *share of files containing the pattern*. Bounded by construction, and
  interpretable at any repository size.
- **Per-function patterns** (`decorator`, `type_hints`, `recursion`, `async`,
  `star_args`, `keyword_only_args`, `generator_function`, `nested_function`,
  `property`, `static_or_class_method`) →
  *share of functions*. "What fraction of your functions are decorated" is a
  meaningful quantity; "what fraction of your files contain a decorator" is not.

Self-profiling now gives a usable spread: type hints 97%, f-strings 89%,
comprehensions 78%, try/except 44%, classes 28%.

Full write-up: [M2 in S001](../journal/2026-08-08-S001-core-loop.md#m2--pattern-frequency-can-be-normalised-by-dividing-by-file-count).

## Tags

Libraries and patterns collapse into content tags, which are the only part of
the vector that level selection reads:

```
pandas, numpy, csv, polars     → data, tabular, numeric
requests, httpx, bs4, scrapy   → web, http, scraping
flask, fastapi, django         → web, server
itertools, functools, operator → functional
heapq, bisect, collections     → algorithms, datastructures
asyncio                        → async
```

A pattern earns its tag only above a threshold (35%), so one stray comprehension
does not make someone a functional programmer.

## Recommendation: gaps over comfort

```python
score = 0.4 × comfort + 0.6 × gap
```

where `comfort` is the share of a level's tags the player already uses, and
`gap` is the share they do not.

**The weighting leans toward gaps on purpose.** The stated goal of the Vibe
Vector in the design document is to *fill knowledge gaps* — a game that only
serves you what you are already good at is a leaderboard, not a teacher.
Comfort still carries 40% so the queue stays recognisable rather than throwing a
pandas-only player straight into async on day one.

Levels with no tags sort last. Without a profile, ordering falls back to
campaign order.

## The style signature

The numbers are the evidence; the signature is the sentence somebody reads.
`docstring_ratio 0.43` tells a player nothing about themselves. *"untyped,
loop-first, %-format era, long functions"* — which is what this profiler says
about the standard library's `json` — tells them something they can recognise
and argue with, and arguing with it means they looked.

Every threshold is a judgement about **style, never quality**. A codebase with
deep nesting and no type hints is not being marked down; the profiler's job is
to describe how somebody writes so the game can meet them there. A signature
that read as a scolding would make people stop running it.

## What it deliberately does not measure

**Skill.** The Vibe Vector describes *habits*, not *ability*. Someone who uses
`pandas` in every file may still be bad at it.

Performance measurement is a separate model, deliberately kept separate, and it
belongs to [T4](trajectories/T4-adaptive.md). Merging the two is the most
tempting simplification available here and the most wrong: it would let the game
conclude you are good at something purely because you do it often.
