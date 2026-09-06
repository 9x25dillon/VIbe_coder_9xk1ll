# S012 — The archive we refuse to open

**Date:** 2026-09-06 · **Duration:** — · **Trajectory:** T2 (W5) ·
**Competency band:** `Create` ·
**Data:** [`data/sessions/2026-09-06-S012.json`](../data/sessions/2026-09-06-S012.json)

## Objectives

| # | Objective | Result |
| --- | --- | --- |
| 1 | A `.zip` of a codebase profiles, and profiles the same as the directory | ✅ met |
| 2 | A zip bomb is refused before anything is expanded | ✅ met |
| 3 | No source reaches the disk, provably rather than by cleanup | ✅ met |
| 4 | A rejected archive tells the player which rule it broke | ✅ met |
| 5 | The vibe panel stays square when the path is long | ✅ met |

## What was built

### `ingest.py` — the boundary, with nothing behind it

`vibecoder profile` now accepts an archive as well as a directory. Two
structural choices do most of the safety work, and both are properties of the
shape rather than of care taken:

**Nothing is written to disk.** Members are decompressed into memory, parsed,
and dropped. There is no extraction directory, so there is no cleanup step that
can fail — which is how T2's "no source retained afterwards" commitment is met
for this path. It also makes path traversal *unreachable*: `../../.ssh/id_rsa`
is a string we reject, not a file we nearly wrote.

**Only `.py` members are ever opened.** A nested archive, a 4 GB blob of zeros,
an ELF binary — none are read, because the profiler has no use for them. The
classic zip-of-zips bomb is not defended against so much as never entered.

What remains is a two-stage guard. The central directory is judged **before a
byte is decompressed** — a bomb detected while inflating has already cost what
it set out to cost — across six limits: archive size, entry count, declared
total expansion, per-member expansion, total source read, and compression
ratio. The ratio only applies above a 1 MB floor, because a 12 KB file that
compresses 200:1 is a text file full of spaces and not an attack.

Rejection fails the **whole archive**, not the offending member. An archive
holding a traversal entry is not a codebase with one odd file in it, and
profiling the rest would amount to deciding that hostile input is acceptable
as long as it is handled neatly.

`ingest.py` imports nothing from the package, for the same reason `_harness.py`
does not (N2): it is where untrusted input arrives, and it should be readable
and testable without the game around it.

### The profiler grew a seam

`profile_path` did two jobs — finding files and analysing them — and only the
second is about profiling. The analysis core is now `profile_sources`, which
sees `(label, text)` pairs and knows nothing about where they were stored. A
directory, an archive, and whatever W4 eventually clones from GitHub all reduce
to it. Archives route by *content* rather than by extension, via the
end-of-central-directory record, so a `.whl`, an `.egg` and a download that lost
its suffix all behave alike.

### A box that was not square

Profiling an archive out of a long path printed a `source` line straight
through the right-hand border of the vibe panel. `UI.box` is not at fault — its
documented contract is lines of known width — so the fix is in `cmd_profile`,
which now elides the path from the left, keeping the tail that names the file.
The marker is ASCII rather than `…` so the width cannot depend on the terminal's
Unicode support, which is T6's rule.

This is pre-existing: a long enough *directory* has always been able to do it.
An archive in `~/Downloads` only made it ordinary.

## Evidence

```
$ python3.11 -m unittest discover -s tests
Ran 660 tests in 38.862s — OK

$ python3.11 -m vibecoder.cli verify --seeds 3
36/36 reference runs clean

$ python3.11 -m vibecoder.cli showcase | grep -c $'\033'
0

$ python3.11 -m vibecoder.cli profile /tmp/.../repo.zip     # this package, zipped
files 36   functions 356   code lines 6678
strongly typed / comprehension-first / f-string era / shallow nesting     exit 0

$ python3.11 -m vibecoder.cli profile /tmp/.../bomb.zip     # 1 GiB in 1.02 MiB
rejected archive  'payload.py' declares 1,073,741,824 bytes, over the
                  4,194,304 byte per-file limit                          exit 2
```

| Claim | Evidence | Verdict |
| --- | --- | --- |
| An archive profiles identically to the directory | `test_an_archive_profiles_identically_to_the_directory`, whole vector compared | verified |
| A real 1 GiB bomb is rejected | `TestTheBombGuard`, specimen built by deflating a gibibyte | verified |
| It is rejected *before* any member is opened | `ZipFile.open` patched to raise; rejection still occurs | verified |
| Rejection is decided from the directory, so it is immediate | `inspect_zip` on the bomb, asserted under 1 s | verified |
| A bomb spread thinly across legal-sized members is caught | `test_the_ratio_guard_catches_a_bomb_spread_across_members` | verified |
| An ordinary well-compressing file is not a bomb | `test_a_small_well_compressing_file_is_not_a_bomb` | verified |
| Traversal, absolute, backslash and drive-letter names are refused | five tests in `TestRejection` | verified |
| One hostile member fails the whole archive | `test_a_hostile_member_fails_the_whole_archive` | verified |
| Symlink and encrypted members are skipped, not read | two tests, flag bits forged by hand | verified |
| A nested archive is never opened | `test_a_nested_archive_is_never_opened` | verified |
| No extraction API is called at all | `extract`, `extractall` and `mkdtemp` patched to raise | verified |
| The filesystem is unchanged after profiling an archive | `test_profiling_an_archive_leaves_the_filesystem_as_it_found_it` | verified |
| The read is bounded by our limit, not by the declaration | `read` spied on; called once with `max_file_bytes + 1` | verified |
| A reader that ignores the declared size is still caught | `ZipExtFile.read` patched to over-return | verified |
| The panel box has one width with a long path | `test_the_rendered_box_has_one_width`; fails 64 ≠ 131 without the fix | verified |
| Rejection exits 2 and prints a reason rather than a traceback | run by hand, above | verified |
| The limits are right for real repositories | only this package and its own tests were profiled from an archive | `UNVERIFIED` — plausible, not measured |

### Against T2's exit criteria

- **4 — a zip bomb (≤1 MB compressed, ≥1 GB expanded) is rejected before
  expansion:** met, with a caveat worth recording. Deflate tops out near
  1032:1, so a single-stream 1 GB bomb *cannot* compress below ~1.02 MB. The
  specimen is 1 GiB expanded in 1,043,756 bytes, which satisfies the criterion
  read in binary units and misses it by 4% read in decimal ones. The criterion
  was not edited (N7); this is the finding it produced.
- **5 — no source retained on disk, verified by inspecting the working
  directory:** met for the archive path, and by a stronger method than the
  criterion asks for. Inspecting the directory afterwards is compatible with
  extracting and deleting, and a deletion is a step that can fail; the test
  asserts the extraction API is never called at all. The criterion stays open
  until W4's clone path exists to be checked.

## Misconceptions and corrections

### M25 — the forged central directory was the dangerous case

**Believed:** The central-directory checks all trust numbers written by whoever
built the archive, so the real attack is a header that lies: declare 1 KB,
ship 256 KB, and inflate past every limit that was decided from the
declaration. The bounded read in the streaming stage was written as the guard
that mattered, and a test was written to prove it fires.

**Revealed by:** The test failing to raise. `zipfile.ZipExtFile.__init__` sets
`self._left = zipinfo.file_size` and bounds decompression output by it, then
checks the directory's CRC against what it inflated. A member physically cannot
expand past its declaration through that reader — and an under-declared member
fails its CRC and is dropped entirely. Forging a size costs the forger that
member and buys nothing.

**Corrected to:** The central-directory checks *are* the guard, and they are
sound. The bounded read stays, because `ZipExtFile` bounding itself is an
implementation detail of one interpreter rather than a documented contract —
but it is defence against an assumption, not against an attack, and the test
now says so by simulating a reader that does not bound itself.

**Cost:** ~20 minutes. The valuable part is that the test I wrote to confirm
what I believed is what disproved it; three passing tests around a wrong mental
model would have shipped happily.

### M26 — "the baseline is green" from a run that skipped the check

**Believed:** The pinned forty-second suite is the inner loop, and green there
means green.

**Revealed by:** Doing arithmetic on test counts. 612 documented, 48 added, and
discovery reporting 655 — which would mean the count had already drifted and
`test_living_docs_quote_the_real_test_count` was red before I started. It
*skips* when `VIBECODER_SANDBOX` is pinned, which is exactly how it had run.

**Corrected to:** Nothing was wrong. The 655 was my own stale measurement,
taken before the last five tests existed; the real count is 660 and 612 was
correct. But the reasoning that produced the false alarm is sound and worth
keeping: the fast loop skips a check that only the unpinned run performs, so
"green" from a pinned run is a weaker claim than it reads as. CLAUDE.md already
says to commit against the unpinned run. It does not say the pinned run cannot
see doc drift, and that is the sentence that would have saved the detour.

**Cost:** ~10 minutes, and it produced a real correction to a number I had
already written into two documents.

## Friction

- The 1 GiB specimen takes ~3 s to build because deflate has to actually
  compress a gibibyte. Built once per test class rather than per test. A forged
  central directory would be instant and would prove less — the point is that a
  *real* bomb is refused.
- `zipfile` cannot write an encrypted member and `writestr` discards a
  `ZipInfo`'s `flag_bits`, so the encrypted-member test sets bit 0 by hand in
  both the local and central headers. Worth the byte-poking: a
  password-protected archive is an ordinary thing for somebody to upload.

## Decisions

| # | Decision | Alternatives considered | Rationale | Reversible? |
| --- | --- | --- | --- | --- |
| D70 | Archives are read into memory; nothing is extracted | Extract to a temp dir, profile, delete | A cleanup step can fail. No extraction means no window, and it makes traversal unreachable rather than defended | yes |
| D71 | Only `.py` members are ever opened | Extract everything, filter afterwards | Shrinks the decompression surface to the one thing we want, and never enters a zip-of-zips | yes |
| D72 | The central directory is judged before any expansion | Guard while inflating | A bomb caught mid-inflate has already cost what it set out to cost | no — this is the criterion |
| D73 | One hostile member fails the whole archive | Skip it and profile the rest | An archive containing a traversal is not a codebase with one odd file in it | yes |
| D74 | Archives route by content, not by extension | Match `.zip` | A `.whl`, an `.egg` and a suffix-less download are all archives; a `.py` never is | yes |
| D75 | `ingest.py` imports nothing from the package | Put it in `profiler.py` | Same reason as N2 for `_harness.py`: the boundary where untrusted input arrives should be readable without the game around it | yes |
| D76 | `SKIP_DIRS` filtering stays in `profiler`, not `ingest` | Filter inside `ingest` | Which directories are uninteresting is a fact about profiling, not about zip files — and the byte budget should cover the whole archive | yes |
| D77 | The path elision marker is ASCII `...` | A `…` glyph in `GLYPHS` | Every existing glyph pair is one character wide in both modes; a 1-vs-3 pair would change the layout between capabilities | yes |

## Handoff

- **State:** T2 W5 is landed. `vibecoder profile` reads a `.zip` (or any
  archive, detected by content), expands nothing to disk, and refuses hostile
  archives from the central directory with a named reason and exit code 2.
  660 tests green unpinned, `verify` clean on 36 reference runs, `showcase`
  prints zero escapes in a pipe.
- **⚠ Use Python 3.11 on this machine** — see M5 in S003. Unchanged.
- **Next action:** **T2 W6** — ingestion limits with a *partial* profile.
  `IngestLimits` already carries the size and count budgets W6 needs; what is
  missing is the wall-clock budget and, more substantially, the ability for
  `VibeVector` to say it is partial. A 5,000-file repository must degrade to a
  flagged partial profile rather than hang (exit criterion 6). Note that
  W6 touches what is stored about a player, so the `partial` flag on the vector
  is a §12 "ask first" change.
- **Blockers:** W4 remains blocked on a registered OAuth application and the
  client-versus-server profiling decision. Unchanged.
- **Context required:** D70 before adding any extraction step — the "no source
  on disk" property is structural and easy to lose by accident. D72 before
  moving any check into the streaming stage. M25 before deciding the bounded
  read is redundant and deleting it.

## Open questions

| # | Question | Owner trajectory | Status |
| --- | --- | --- | --- |
| Q44 | The limits were chosen from what a source repository plausibly costs, and validated against exactly one archive: this package. Do 500 MB declared and 50,000 entries clear a real monorepo, and is a 4 MB per-file cap too tight for a codebase with a large generated module? | T2 | open |
| Q45 | Exit criterion 4's numbers — ≤1 MB compressed, ≥1 GB expanded — are only jointly reachable in binary units, because deflate cannot exceed ~1032:1. Should the criterion say MiB/GiB, or should the specimen use a format with a higher ceiling? Editing it is N7-forbidden; recording the finding is not. | T2 | open |
| Q46 | `max_source_bytes` is the only limit enforced during streaming, so it is the only one whose rejection arrives after work has been done. Should a partial profile be returned at that point instead of an exception — and is that W6's answer rather than W5's? | T2 | open |
| Q47 | An archive is recognised by content, so `vibecoder profile foo.py` on a file that happens to be a zip profiles its members instead of the file. That is correct and surprising. Should the panel say which route was taken? | T2 | open |
