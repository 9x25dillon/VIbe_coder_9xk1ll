# Data

Machine-readable records, ordered chronologically by filename. Everything here
is committed, append-mostly, and safe to parse without running the game.

```
data/
├── schema/
│   ├── session-review.schema.json   structure of a session record
│   └── baseline.schema.json         structure of a measurement baseline
├── sessions/                        one record per working session
│   └── YYYY-MM-DD-Snnn.json
└── baselines/                       measurements taken at a point in time
    └── YYYY-MM-DD-<name>.json
```

## Sessions

Each file is the structured twin of a [journal entry](../journal/). The
Markdown carries reasoning; the JSON carries facts. They are written together
and must agree — if they disagree, the JSON is wrong, because prose is where
thinking happens and the record is derived from it.

Naming is `YYYY-MM-DD-Snnn.json`, so `ls` gives chronological order and a
session id is greppable across the whole repository.

Query it like any other data:

```bash
# every misconception recorded so far, newest last
jq -r '.misconceptions[] | "\(.id)  \(.believed)"' data/sessions/*.json

# which trajectories have had sessions spent on them
jq -r '.trajectory' data/sessions/*.json | sort | uniq -c

# open questions across the project
jq -r '.open_questions[] | select(.status=="open") | "\(.id) [\(.owner)] \(.question)"' \
   data/sessions/*.json
```

## Baselines

A baseline is a set of numbers measured at a moment, kept so that later changes
can be compared against something real rather than against memory. They are
never edited after the fact — a new measurement is a new file. That is what
makes a regression visible.

```bash
# op counts for every level reference, first vs latest baseline
jq -s '.[0].levels, .[-1].levels' data/baselines/*.json
```

## Rules

1. Files here are **immutable once committed**. Correcting a record means
   adding a new one that supersedes it and saying so in its `supersedes` field.
2. No file in this directory may contain source code from a player's codebase,
   an access token, or a repository URL that is not public. The Vibe Vector is
   derived statistics and is safe to store; its input is not.
3. Every field in a schema is required. Absent information is written
   explicitly (`null`, `[]`, `"none"`) so that a missing field always means a
   bug rather than an omission.
