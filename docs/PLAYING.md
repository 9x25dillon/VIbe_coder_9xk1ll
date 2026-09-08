# Playing a boss fight

A walkthrough of `w1-boss-pipeline` from the starter to a cleared fight, plus
what to look at while you play. This is a **playtest guide** as much as a
tutorial: several of the numbers in here were chosen by argument rather than by
anyone actually playing, and the last section says which ones and what would
change them.

> **Use Python 3.11.** `python3` on this machine is 3.14 and the game is
> developed against 3.11 — see M5 in
> [S003](../journal/2026-09-03-S003-sandbox-seam.md).

---

## 1. Start the fight

```bash
python3.11 -m vibecoder.cli boss w1-boss-pipeline --live
```

That is the whole command. No `--solution`, no `--fix` — you are going to write
the code yourself, in the game.

**It has to be a real terminal.** The repair editor needs a TTY on both stdin
and stdout, so piping the output (`| less`, `> log.txt`) turns the fight into a
spectator sport: it still runs, it just never offers you the editor.

If the tracing is too fast or too slow, `--speed` is seconds per line and
defaults to `0.35`. `--speed 0` runs it flat out, which is what you want on a
second play-through.

---

## 2. What you are looking at

```
── BOSS  The Feed  (live) ──────────────────────────────────────────────────

  boss ████████████████████ 100   repairs ●●●●●

  Parse the feed  parse_rows()
      3 ▸ lines = ['widget,25.0,2', 'sprocket,3.5,10', ...
      4 ▸ rows = []
      5 ▸ line = 'widget,25.0,2'
      6 ▸ quantity = '2'
     11 ▸ rows = [{'name': 'widget', 'price': 25.0, 'quantity': 2}]
```

| What | Meaning |
| --- | --- |
| `boss ████… 100` | The boss's health. It starts at 100 and only a flawless fight takes it to 0 |
| `repairs ●●●●●` | Your pool. Five filled pips, one spent per repair, and `·` for a spent one |
| `  3 ▸ rows = []` | The line that just ran, and the local variable that **changed** because of it |

Your code runs **one line at a time in a real interpreter**, not a recording.
The number on the left is the line in your file; the text on the right is what
moved. A loop is shown for three laps and then fast-forwarded, because a loop
seen four times has taught what it is going to teach.

---

## 3. The fight is three linked functions

`w1-boss-pipeline` is a supplier feed, in three moves:

| Step | Function | What it does |
| --- | --- | --- |
| 1 | `parse_rows(lines)` | Turn `'name,price,quantity'` strings into dicts |
| 2 | `above_floor(rows, floor)` | Keep the rows priced at or above `floor` |
| 3 | `summarise(lines, floor)` | Use both of the above; report count and revenue |

They share one file. Step 3 **calls** steps 1 and 2 — that is the point of a
boss rather than three separate levels. Each step is graded on its own tests,
so a mistake in step 1 cannot fail step 3 and tell you the wrong thing.

You start with only step 1's stub. **Each step's stub is added to your file
when you reach it**, and everything you have already written is kept exactly as
you wrote it.

---

## 4. Your first failure

**The starter runs.** It is not an empty stub — it is code that does real work
and gets it wrong, which is the only kind of code worth watching:

```python
def parse_rows(lines):
    """Turn 'name,price,quantity' lines into dicts."""
    rows = []
    for line in lines:
        name, price, quantity = line.split(",")
        rows.append({
            "name": name,
            "price": float(price),
            "quantity": int(quantity),
        })
        return rows        # ← look at where this is
    return rows
```

Watch the trace in section 2 again. It enters the loop, builds one dict, and
**returns on the first lap** — you can see `rows` holding exactly one row when
it stops. That is the bug, and you found it by watching rather than by reading.

```
    50% of cases pass

── WHAT WENT WRONG ─────────────────────────────────────────────────────────

  given       ['widget,25.0,2', 'sprocket,3.5,10', 'gasket,12.25,4', ...]
  expected    [{'name': 'widget', 'price': 25.0, 'quantity': 2}, ...]
  you gave    [{'name': 'widget', 'price': 25.0, 'quantity': 2}]
```

Half the cases pass, because the one-row and empty-list cases do not care that
the loop stops early. Then the editor opens.

---

## 5. The repair pane

```
─ FIX Parse the feed parse_rows() ────────────────────────────────────────────
 ✘ line 1: expected [{'name': 'widget', 'price': 25.0, 'quantity': 2}, {'name'

──────────────────────────────────────────────────────────────────────────────
 ✘  1 def parse_rows(lines):
    2     """Turn 'name,price,quantity' lines into dicts."""
    3     rows = []
    4     for line in lines:
    5         name, price, quantity = line.split(",")
    6         rows.append({
   ...
   11         return rows
   12     return rows
──────────────────────────────────────────────────────────────────────────────
 ctrl-r resume   ctrl-z undo   ctrl-k kill line   ctrl-x give up
```

The cursor is already on the line that went wrong. **These are the same keys as
the level editor** (`vibecoder edit`), so if you have used that, you already
know this.

| Key | Does |
| --- | --- |
| `ctrl-r` | Apply the fix and carry on with the fight |
| `ctrl-z` / `ctrl-y` | Undo / redo |
| `ctrl-k` | Kill to end of line — press again to swallow the next line |
| `ctrl-a` / `ctrl-e` | Start / end of line |
| `ctrl-x` | Give up on the fight |
| arrows, `home`, `end`, `tab` | As you would expect |

Two things worth knowing:

- **Take as long as you like.** The paused process is genuinely paused, and its
  time budget counts only executing time. A fight cannot time out because you
  thought about it.
- **A fix that will not compile does not cost you anything.** `ctrl-r` compiles
  first and tells you where the syntax error is instead of spending your
  repair.

### The fix for step 1

The whole repair is **deleting line 11** — the `return rows` that sits inside
the loop. Move to it, `ctrl-k` twice to swallow the line, and `ctrl-r`.

If you would rather rewrite the function, the cursor starts on
`def parse_rows`, so holding `ctrl-k` clears from there to the end of the file
and you can type or paste a replacement:

```python
def parse_rows(lines):
    """Turn 'name,price,quantity' lines into dicts."""
    rows = []
    for line in lines:
        name, price, quantity = line.split(",")
        rows.append({"name": name, "price": float(price), "quantity": int(quantity)})
    return rows
```

---

## 6. What a repair costs you

This is the part to pay attention to, because it is the mechanic.

```
    repaired — the boss recovers 5  (accuracy 50%)
    ▶ running the step again with your fix
    ✔ cleared after 1 repair   -16
  boss ███████████████████░  89   repairs ●●●●·
```

Spending a repair does **three** things:

1. Takes a pip from your pool. You get five.
2. **Halves the damage that step will deal**, compounding — a second repair on
   the same step leaves it worth a quarter.
3. **Heals the boss**, by an amount scaled by how wrong your code was.

That third one is the interesting one, and the direction is deliberate:

| What you repaired | Accuracy | Boss recovers |
| --- | --- | --- |
| Nearly right | 90% | 1 |
| Half working | 50% | 5 |
| A guess | 0% | 10 |

**Being close is rewarded.** Patching something that almost worked costs the
boss almost nothing. Repairing a guess hands it a real recovery, and over five
repairs that difference is about half its health. It is the same argument the
Functional axis rests on: the game scores *how* you got there, not just that
you arrived.

### Two ways to end

| Ending | Means |
| --- | --- |
| `BOSS DOWN` | Health reached exactly 0 — only possible with **no repairs spent at all** |
| `BOSS SURVIVES` | You cleared every step, and it is still standing |

Both exit `0`. You won the fight either way; `BOSS DOWN` is the ace.

Running out of repairs ends the fight where it stands. `--repairs N` changes
the pool if you want to make it easier or brutal — `--repairs 0` means the
first mistake is final.

---

## 7. Steps 2 and 3

When step 1 clears, `above_floor`'s starter appears in your file and the fight
carries on. Both are the same shape as step 1: code that runs, with one thing
wrong.

**Step 2** ships as `row["price"] > floor`. Its brief warns you — *"the floor
itself counts as qualifying"* — and exactly one test case sits on the
boundary, so it passes **83%** and the repair costs the boss almost nothing.
That is the heal curve doing its job: nearly right is nearly free.

```python
def above_floor(rows, floor):
    """Keep rows priced at or above `floor`."""
    return [row for row in rows if row["price"] >= floor]
```

**Step 3** ships wired up correctly and counting the wrong thing — revenue as
the sum of *prices*, ignoring how many of each you have. The pane tells you
precisely that: `expected {'count': 3, 'revenue': 159.0}, got {'count': 3,
'revenue': 97.25}`. The count is already right.

```python
def summarise(lines, floor):
    """Parse, filter, and report count and revenue."""
    kept = above_floor(parse_rows(lines), floor)
    return {
        "count": len(kept),
        "revenue": round(sum(r["price"] * r["quantity"] for r in kept), 2),
    }
```

`summarise` calls the two functions **you** wrote. If yours are wrong in a way
their own tests missed, you find out here.

---

## 8. Things worth trying deliberately

| Try | What you should see |
| --- | --- |
| Solve all three first try | `BOSS DOWN`, health exactly 0, all five pips left |
| Break a line **above** the one that failed, then resume | `replay diverged: …` and a warning that the re-run is not a continuation of what you watched |
| `ctrl-r` on code with a syntax error | It refuses, names the line, and does **not** spend a repair |
| Open the pane and `ctrl-x` | No repair spent — giving up is not the same as fixing |
| `--repairs 1` | The second failure ends the fight |
| `--speed 0` | The whole fight at full tilt |
| `--reference` | Watch a perfect run, to see what the trace looks like when nothing is wrong |
| Pipe it: `… --live \| cat` | Runs to the first failure and stops — no editor without a TTY |

---

## 9. What is genuinely unverified

Being straight about this, since you are the first person to play it. The
mechanics are tested; the *feel* is not.

- **Nobody has played a fight with health on it before you.** Every number in
  section 6 was chosen by argument and checked by unit tests. None of them has
  been watched over a shoulder.
- **`BOSS DOWN` is out of reach from the starters, and that is now the
  design.** Every starter fails its own tests — that is the level contract,
  and it exists so a starter cannot hand out a free step — so every step costs
  at least one repair. Playing the three starters straight through lands the
  boss on exactly **65**, measured. `BOSS DOWN` is what you come back for,
  with a solution that passes every step first time; a first run is graded by
  the scorecard, not by an ending it could not reach. (Q80, resolved; the
  reasoning and the measured floor are in
  [`SCORING.md`](SCORING.md#boss-down-is-a-mastery-ending-not-a-first-run-one-q80).)
- **Five repairs is a guess.** It is meant to be enough to survive a bad step
  or two and not enough to brute-force three. That band is a claim, not a
  measurement. (Open question Q76.)
- **The 10% heal ceiling is a guess** in the same way. The *direction* — closer
  is cheaper — is the design and should not change. The magnitude is a dial.
- **`0.35s` per line and three loop laps** were set before there was a fight to
  pace, in [S017](../journal/2026-09-06-S017-live-stepping.md).
- **The scorecard's feel is unplayed.** The fight *is* scored now, on the same
  three axes as a level at 40/30/30 (T3 W7) — but like everything else in this
  section, the numbers were chosen by argument and checked by unit tests, and
  nobody has watched one land at the end of a real fight.

If something feels wrong, the useful report is what you *expected* to happen
and what happened instead — that is the shape a journal entry can act on. The
numbers all live in
[`SCORING.md`](SCORING.md#boss-fights-hit-points-and-repairs-t3-w6) with the
reasoning attached, so changing one means changing the argument for it too.

---

## Related

- [`ARCHITECTURE.md`](ARCHITECTURE.md) — how the live stepping, the resume and
  the repair pane actually work
- [`SCORING.md`](SCORING.md) — every number, with the reason it was chosen
- [`T3`](trajectories/T3-boss-engine.md) — the trajectory this fight belongs to
