"""Keyboard campaign browser, sharing the editor's terminal and visual rules."""

from __future__ import annotations

from dataclasses import dataclass

from . import cockpit
from .keys import Key, KeyDecoder
from .keymap import binding
from .screen import Screen
from .term import MIN_HEIGHT, MIN_WIDTH, TerminalSession, supported
from .ui import ACCENT, BAD, GOLD, GOOD, INK, MUTED, Renderer, detect


@dataclass
class Campaign:
    """Selection is UI state only; browsing never changes a player's profile."""

    levels: list
    bosses: list
    session: object
    ui: Renderer
    selected: int | None = None

    def __post_init__(self) -> None:
        self.entries = []
        for world in sorted({level.world for level in self.levels}):
            self.entries.extend(("level", level) for level in self.levels if level.world == world)
            self.entries.extend(("boss", boss) for boss in self.bosses if boss.world == world)
        self.next_index = next((index for index, (kind, item) in enumerate(self.entries)
                                if kind == "level" and not getattr(self.session.levels.get(item.id), "best_stars", 0)), None)
        if self.selected is None:
            self.selected = self.next_index or 0
        self.scroll = 0
        self.running = True
        self.choice = None
        self.details_open = False
        self.detail_scroll = 0

    def compose(self, rows: int, columns: int) -> Screen:
        """One responsive frame, including explicit empty and small states."""
        screen = Screen(rows, columns)
        if rows < MIN_HEIGHT or columns < MIN_WIDTH:
            cockpit.put(screen, 0, 0, f"{columns}x{rows} too small; need {MIN_WIDTH}x{MIN_HEIGHT}", columns)
            return screen
        cockpit.header(screen, self.ui, "VIBECODER / CAMPAIGN", "Choose your next challenge")
        cockpit.divider(screen, self.ui, 1)
        if not self.entries:
            screen.put(3, 2, "No challenges available.", self.ui.style(MUTED))
            return screen
        self.selected = max(0, min(self.selected, len(self.entries) - 1))
        kind, item = self.entries[self.selected]
        wide = columns >= cockpit.WIDE
        list_width = columns // 2 if wide else columns
        height = rows - 5 if wide else max(3, (rows - 5) // 2)
        if self.details_open:
            self.detail_scroll = cockpit.document(
                screen, self.ui, self._details(kind, item, columns - 4),
                top=3, left=2, height=rows - 5, width=columns - 4,
                offset=self.detail_scroll,
            )
        else:
            self.scroll = min(self.scroll, self.selected)
            self.scroll = max(self.scroll, self.selected - height + 1)
            for index in range(self.scroll, min(len(self.entries), self.scroll + height)):
                entry_kind, entry = self.entries[index]
                record = self.session.levels.get(entry.id)
                stars = record.best_stars if record else 0
                state = "BOSS" if entry_kind == "boss" else ("DONE" if stars else ("NEXT" if index == self.next_index else "OPEN"))
                marker = ">" if index == self.selected else " "
                label = f"{marker} W{entry.world}  {state:<4}  {entry.title}"
                tone = ACCENT if index == self.selected else (BAD if entry_kind == "boss" else INK)
                cockpit.put(screen, 3 + index - self.scroll, 2, label, list_width - 4,
                            self.ui.style(tone, bold=index == self.selected))
            left, top = (list_width + 2, 3) if wide else (2, 3 + height)
            width = columns - left - 2
            cockpit.document(screen, self.ui, self._details(kind, item, width),
                             top=top, left=left, height=rows - top - 2, width=width, more="ctrl-o expand")
        cockpit.divider(screen, self.ui, rows - 2)
        keys = "Up/Down select  Enter play  ctrl-o details  Esc quit"
        if columns < 60:
            keys = "Up/Down select  Enter play  ^O info  Esc quit"
        if self.details_open:
            keys = "PgUp/PgDn scroll  Enter play  Esc back"
        cockpit.put(screen, rows - 1, 1, keys, columns - 2, self.ui.style(ACCENT))
        return screen

    def _details(self, kind, item, width):
        record = self.session.levels.get(item.id)
        lines = cockpit.section(item.title.upper(), item.id, width)
        if kind == "level":
            lines += [(f"WORLD {item.world} / {item.world_title}", MUTED)]
        if kind == "boss":
            lines += [(f"BOSS ENCOUNTER / {item.step_count} steps", BAD), ("", INK)]
        elif record and record.best_stars:
            lines += [(f"BEST {record.best_total:.1f} / {record.best_stars} of 3 stars", GOLD), ("", INK)]
        else:
            lines += [("UNPLAYED / ready when you are", GOOD), ("", INK)]
        lines += cockpit.section("OBJECTIVE", item.brief, width)
        lines += cockpit.section("CONCEPTS", ", ".join(item.tags), width)
        return lines

    def handle(self, key: Key) -> None:
        """Navigate without letting a detail-view keystroke select another level."""
        command = binding(key)
        if command in ("ctrl-x", "ctrl-c") or (command == "escape" and not self.details_open):
            self.running = False
        elif command in ("ctrl-o", "escape"):
            self.details_open = not self.details_open
            self.detail_scroll = 0
        elif command == "enter" and self.entries:
            self.choice = self.entries[self.selected]
            self.running = False
        elif command in ("up", "pgup", "down", "pgdn"):
            delta = -1 if command in ("up", "pgup") else 1
            if self.details_open:
                self.detail_scroll = max(0, self.detail_scroll + delta * (8 if command.startswith("pg") else 1))
            elif self.entries:
                self.selected = max(0, min(len(self.entries) - 1, self.selected + delta))


def choose(levels, bosses, session, selected: int | None = None):
    """Return the chosen challenge after restoring the terminal, or None."""
    if not supported():
        raise RuntimeError("campaign browsing needs a terminal; use levels --map for a text map")
    browser = Campaign(list(levels), list(bosses), session, Renderer(detect()), selected)
    decoder = KeyDecoder()
    previous = None
    with TerminalSession() as terminal:
        while browser.running:
            if terminal.resized:
                previous = None
            frame = browser.compose(*terminal.size())
            patch, _, _ = frame.diff(previous)
            terminal.write(patch)
            previous = frame
            data = terminal.read(0.1)
            for key in decoder.feed(data) if data else decoder.flush():
                browser.handle(key)
    return browser.choice, browser.selected
