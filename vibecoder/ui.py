"""Terminal presentation layer.

Everything the game draws goes through here. The module's job is to render the
same information at whatever fidelity the output stream can actually take:
truecolor gradients and animation on a modern terminal, plain ASCII when piped
to a file, and the identical *layout* in both.

Three rules shape the design.

1. **Capability is detected, never assumed.** A pipe, a CI log and an iTerm
   window are different targets. Escape codes leaking into a log file is a bug,
   and S001 recorded the previous hard-coded approach as friction.
2. **Width is a parameter, not a global.** Elements take the width they may use
   rather than reading the terminal at draw time, which is what makes them
   testable at any size.
3. **Colour is the last thing applied.** Every element computes its plain-text
   layout first and paints afterwards, so the visible output is byte-identical
   across colour depths. The test suite asserts exactly that.

No third-party dependencies (N1). ANSI escape sequences are simple enough to
emit directly, and doing so keeps the rendering inspectable.
"""

from __future__ import annotations

import os
import shutil
import sys
import time
from dataclasses import dataclass
from enum import IntEnum
from typing import Iterable, Sequence

# --------------------------------------------------------------------------
# Capability detection
# --------------------------------------------------------------------------


class Depth(IntEnum):
    """Colour fidelity of an output stream, in ascending order."""

    NONE = 0
    ANSI16 = 1
    ANSI256 = 2
    TRUECOLOR = 3


@dataclass(frozen=True)
class Capabilities:
    depth: Depth
    unicode: bool
    animate: bool
    width: int

    @property
    def colour(self) -> bool:
        return self.depth > Depth.NONE


PLAIN = Capabilities(depth=Depth.NONE, unicode=False, animate=False, width=80)
"""Deterministic capabilities for tests and for anything that must not surprise."""


def detect(stream=None) -> Capabilities:
    """Work out what ``stream`` can render.

    Honours the conventions users expect: ``NO_COLOR`` disables colour outright,
    ``FORCE_COLOR`` overrides the TTY check for CI systems that render escape
    codes anyway.
    """
    stream = stream or sys.stdout
    tty = bool(getattr(stream, "isatty", lambda: False)())
    forced = os.environ.get("FORCE_COLOR", "").strip()

    if os.environ.get("NO_COLOR") is not None:
        depth = Depth.NONE
    elif forced:
        depth = {"1": Depth.ANSI16, "2": Depth.ANSI256, "3": Depth.TRUECOLOR}.get(
            forced, Depth.TRUECOLOR
        )
    elif not tty or os.environ.get("TERM") == "dumb":
        depth = Depth.NONE
    elif os.environ.get("COLORTERM", "") in {"truecolor", "24bit"}:
        depth = Depth.TRUECOLOR
    elif "256" in os.environ.get("TERM", ""):
        depth = Depth.ANSI256
    else:
        depth = Depth.ANSI16

    encoding = (getattr(stream, "encoding", "") or "").lower()
    unicode_ok = "utf" in encoding

    animate = tty and not os.environ.get("VIBECODER_NO_ANIM")

    return Capabilities(
        depth=depth,
        unicode=unicode_ok,
        animate=animate,
        width=shutil.get_terminal_size((80, 24)).columns,
    )


# --------------------------------------------------------------------------
# Colour
# --------------------------------------------------------------------------

RGB = tuple[int, int, int]

RESET = "\033[0m"

# The 16 basic ANSI colours, used as downgrade targets for any RGB value.
BASIC: list[tuple[RGB, str]] = [
    ((0, 0, 0), "30"), ((170, 0, 0), "31"), ((0, 170, 0), "32"),
    ((170, 85, 0), "33"), ((0, 0, 170), "34"), ((170, 0, 170), "35"),
    ((0, 170, 170), "36"), ((170, 170, 170), "37"),
    ((85, 85, 85), "90"), ((255, 85, 85), "91"), ((85, 255, 85), "92"),
    ((255, 255, 85), "93"), ((85, 85, 255), "94"), ((255, 85, 255), "95"),
    ((85, 255, 255), "96"), ((255, 255, 255), "97"),
]


def _nearest_basic(rgb: RGB) -> str:
    return min(BASIC, key=lambda entry: _distance(entry[0], rgb))[1]


def _distance(a: RGB, b: RGB) -> int:
    return sum((x - y) ** 2 for x, y in zip(a, b))


def _to_256(rgb: RGB) -> int:
    """Map to the xterm 6x6x6 cube, or the greyscale ramp when near-grey."""
    r, g, b = rgb
    if abs(r - g) < 12 and abs(g - b) < 12:
        grey = round((r + g + b) / 3)
        if grey < 8:
            return 16
        if grey > 248:
            return 231
        return 232 + round((grey - 8) / 247 * 23)
    return 16 + 36 * round(r / 255 * 5) + 6 * round(g / 255 * 5) + round(b / 255 * 5)


def sgr(rgb: RGB, depth: Depth, *, background: bool = False) -> str:
    """Build the escape sequence for a colour at a given fidelity."""
    if depth == Depth.NONE:
        return ""
    if depth == Depth.TRUECOLOR:
        layer = 48 if background else 38
        return f"\033[{layer};2;{rgb[0]};{rgb[1]};{rgb[2]}m"
    if depth == Depth.ANSI256:
        layer = 48 if background else 38
        return f"\033[{layer};5;{_to_256(rgb)}m"
    code = _nearest_basic(rgb)
    if background:
        code = str(int(code) + 10)
    return f"\033[{code}m"


def lerp(start: RGB, end: RGB, t: float) -> RGB:
    t = max(0.0, min(1.0, t))
    return tuple(round(a + (b - a) * t) for a, b in zip(start, end))  # type: ignore[return-value]


# Palette. Named roles rather than colour names, so a theme change is one edit.
INK = (218, 218, 224)
MUTED = (128, 128, 140)
FAINT = (78, 78, 88)
ACCENT = (122, 162, 247)
GOOD = (126, 209, 128)
WARN = (231, 179, 96)
BAD = (224, 108, 117)
GOLD = (240, 198, 90)
VIOLET = (187, 154, 247)

# Gradient stops for value-driven colour: 0 is bad, 100 is good.
HEAT_STOPS: list[tuple[float, RGB]] = [
    (0.0, BAD),
    (0.45, WARN),
    (0.75, (180, 200, 120)),
    (1.0, GOOD),
]


def heat(fraction: float) -> RGB:
    """Colour for a 0..1 quality value, interpolated through the heat stops."""
    fraction = max(0.0, min(1.0, fraction))
    for (low, low_rgb), (high, high_rgb) in zip(HEAT_STOPS, HEAT_STOPS[1:]):
        if fraction <= high:
            span = high - low
            return lerp(low_rgb, high_rgb, 0.0 if span == 0 else (fraction - low) / span)
    return HEAT_STOPS[-1][1]


# --------------------------------------------------------------------------
# Renderer
# --------------------------------------------------------------------------

# Glyph pairs: (unicode, ascii). Every visual element degrades rather than
# emitting mojibake on a non-UTF-8 terminal.
GLYPHS = {
    "bar_full": ("█", "#"),
    "bar_empty": ("░", "-"),
    "bar_half": ("▌", "="),
    "star_full": ("★", "*"),
    "star_empty": ("☆", "."),
    "tl": ("╭", "+"), "tr": ("╮", "+"),
    "bl": ("╰", "+"), "br": ("╯", "+"),
    "h": ("─", "-"), "v": ("│", "|"),
    "node_done": ("◆", "@"), "node_open": ("◇", "o"), "node_lock": ("·", "."),
    "link": ("─", "-"),
    "arrow": ("▸", ">"),
    "tick": ("✔", "+"), "cross": ("✘", "x"),
}

SPARKS = "▁▂▃▄▅▆▇█"
SPARKS_ASCII = "._-~=+*#"


class Renderer:
    """Draws every visual element at the fidelity a stream supports.

    Construct with :func:`detect` for real output, or with :data:`PLAIN` for
    deterministic text. All element methods return strings; only the animation
    helpers write to the stream.
    """

    def __init__(self, capabilities: Capabilities = PLAIN, stream=None) -> None:
        self.caps = capabilities
        self.stream = stream or sys.stdout

    # -- primitives --------------------------------------------------------

    def glyph(self, name: str) -> str:
        unicode_glyph, ascii_glyph = GLYPHS[name]
        return unicode_glyph if self.caps.unicode else ascii_glyph

    def paint(
        self,
        text: str,
        rgb: RGB | None = None,
        *,
        bold: bool = False,
        dim: bool = False,
    ) -> str:
        """Apply colour and attributes, or return the text untouched."""
        if not self.caps.colour or not text:
            return text
        prefix = ""
        if bold:
            prefix += "\033[1m"
        if dim:
            prefix += "\033[2m"
        if rgb:
            prefix += sgr(rgb, self.caps.depth)
        return f"{prefix}{text}{RESET}" if prefix else text

    def gauge(
        self,
        value: float,
        *,
        width: int = 24,
        maximum: float = 100.0,
        rgb: RGB | None = None,
    ) -> str:
        """A horizontal bar whose colour tracks its value unless overridden."""
        fraction = 0.0 if maximum <= 0 else max(0.0, min(1.0, value / maximum))
        filled = int(round(width * fraction))
        bar = self.glyph("bar_full") * filled + self.glyph("bar_empty") * (width - filled)
        if not self.caps.colour:
            return bar
        return (
            self.paint(bar[:filled], rgb or heat(fraction))
            + self.paint(bar[filled:], FAINT)
        )

    def gradient_gauge(self, value: float, *, width: int = 24, maximum: float = 100.0) -> str:
        """A bar where every cell is coloured by its own position.

        Only meaningfully different from :meth:`gauge` on a truecolor terminal;
        at lower depths the cells quantise to the same few colours, which is the
        correct degradation rather than a special case.
        """
        fraction = 0.0 if maximum <= 0 else max(0.0, min(1.0, value / maximum))
        filled = int(round(width * fraction))
        if not self.caps.colour:
            return self.glyph("bar_full") * filled + self.glyph("bar_empty") * (width - filled)
        cells = [
            self.paint(self.glyph("bar_full"), heat((i + 1) / width))
            for i in range(filled)
        ]
        cells.append(self.paint(self.glyph("bar_empty") * (width - filled), FAINT))
        return "".join(cells)

    def stars(self, count: int, total: int = 3) -> str:
        earned = self.glyph("star_full") * count
        missing = self.glyph("star_empty") * max(0, total - count)
        return self.paint(earned, GOLD) + self.paint(missing, FAINT)

    def sparkline(self, values: Sequence[float], *, rgb: RGB | None = None) -> str:
        """A one-line chart of a series. Flat series render at the baseline."""
        if not values:
            return ""
        ramp = SPARKS if self.caps.unicode else SPARKS_ASCII
        low, high = min(values), max(values)
        span = high - low
        out = []
        for value in values:
            index = 0 if span == 0 else round((value - low) / span * (len(ramp) - 1))
            out.append(ramp[index])
        return self.paint("".join(out), rgb or ACCENT)

    def rule(self, title: str = "", *, width: int = 72) -> str:
        line = self.glyph("h")
        if not title:
            return self.paint(line * width, FAINT)
        label = f" {title} "
        remaining = max(0, width - len(label) - 2)
        return (
            self.paint(line * 2, FAINT)
            + self.paint(label, MUTED, bold=True)
            + self.paint(line * remaining, FAINT)
        )

    def box(self, lines: Sequence[str], *, title: str = "", width: int = 72) -> list[str]:
        """A bordered panel. ``lines`` must already be plain text of known width."""
        inner = width - 2
        top = self.glyph("tl") + self.glyph("h") * inner + self.glyph("tr")
        if title:
            label = f" {title} "
            top = (
                self.glyph("tl")
                + self.glyph("h")
                + label
                + self.glyph("h") * max(0, inner - len(label) - 1)
                + self.glyph("tr")
            )
        bottom = self.glyph("bl") + self.glyph("h") * inner + self.glyph("br")
        edge = self.glyph("v")
        body = [
            self.paint(edge, FAINT) + f" {line}".ljust(inner) + self.paint(edge, FAINT)
            for line in lines
        ]
        return [self.paint(top, FAINT), *body, self.paint(bottom, FAINT)]

    def badge(self, text: str, rgb: RGB) -> str:
        """A bracketed label.

        The brackets are present at every colour depth rather than standing in
        for colour, so the escape-stripped output is byte-identical whatever the
        terminal supports. A background-filled pill looked better but changed
        the visible text between depths, which breaks T6's exit criterion 6.
        """
        return self.paint(f"[{text}]", rgb, bold=True)

    def banner(self) -> list[str]:
        """The title, in block capitals, tinted across a gradient."""
        art = [
            "@   @ @@@ @@@  @@@  @@@  @@@  @@@  @@@ @@@",
            "@   @  @  @  @ @    @    @  @ @  @ @   @  ",
            "@   @  @  @@@  @@@  @    @  @ @  @ @@@ @@@",
            " @ @   @  @  @ @    @    @  @ @  @ @   @  ",
            "  @   @@@ @@@  @@@  @@@  @@@  @@@  @@@ @@@",
        ]
        block = self.glyph("bar_full")
        out = []
        for row, line in enumerate(art):
            rendered = line.replace("@", block)
            if not self.caps.colour:
                out.append(rendered)
                continue
            out.append(
                "".join(
                    self.paint(char, lerp(ACCENT, VIOLET, col / max(1, len(rendered))))
                    if char != " "
                    else " "
                    for col, char in enumerate(rendered)
                )
            )
        return out

    # -- composite elements ------------------------------------------------

    def axis_row(
        self,
        label: str,
        value: float,
        weight: float,
        detail: str = "",
        *,
        width: int = 24,
    ) -> str:
        """One line of the score breakdown."""
        return (
            f"    {label:<11} {self.gradient_gauge(value, width=width)} "
            f"{value:6.1f}  {self.paint(f'x{weight:.2f}', MUTED)}"
            f"{'  ' + self.paint(detail, FAINT) if detail else ''}"
        )

    def health_bar(
        self,
        current: float,
        maximum: float,
        *,
        width: int = 40,
        label: str = "BOSS",
    ) -> str:
        """Boss health. Built now so T3 renders through the same layer."""
        fraction = 0.0 if maximum <= 0 else max(0.0, min(1.0, current / maximum))
        filled = int(round(width * fraction))
        bar = self.glyph("bar_full") * filled + self.glyph("bar_empty") * (width - filled)
        colour = BAD if fraction > 0.5 else (WARN if fraction > 0.2 else GOOD)
        return (
            f"  {self.paint(label, INK, bold=True)}  "
            f"{self.paint(bar[:filled], colour)}{self.paint(bar[filled:], FAINT)}  "
            f"{self.paint(f'{current:.0f}/{maximum:.0f}', MUTED)}"
        )

    def level_map(self, entries: Sequence[dict], *, width: int = 72) -> list[str]:
        """World progression: one row per world, one node per level.

        ``entries`` are dicts with ``world``, ``world_title``, ``id``, ``title``
        and ``stars``. A node is filled once the level has been cleared.
        """
        rows: list[str] = []
        worlds: dict[int, list[dict]] = {}
        for entry in entries:
            worlds.setdefault(entry["world"], []).append(entry)

        for world in sorted(worlds):
            levels = worlds[world]
            title = levels[0]["world_title"]
            rows.append("")
            rows.append(
                f"  {self.paint(f'WORLD {world}', ACCENT, bold=True)}  "
                f"{self.paint(title, INK)}"
            )
            # Nodes sit on a 6-column pitch (1 node + 5 link characters) and
            # each 3-glyph star label is centred beneath its node, which is why
            # the two rows are indented by 5 and 4 respectively.
            nodes, labels = [], []
            for index, level in enumerate(levels):
                stars = level.get("stars", 0)
                if stars >= 3:
                    node = self.paint(self.glyph("node_done"), GOLD)
                elif stars > 0:
                    node = self.paint(self.glyph("node_done"), GOOD)
                else:
                    node = self.paint(self.glyph("node_open"), FAINT)
                if index:
                    nodes.append(self.paint(self.glyph("link") * 5, FAINT))
                nodes.append(node)
                labels.append(self.stars(stars))
            rows.append("     " + "".join(nodes))
            rows.append("    " + "   ".join(labels))
        return rows

    def bar_chart(
        self,
        items: Sequence[tuple[str, float]],
        *,
        width: int = 22,
        label_width: int = 18,
        maximum: float = 100.0,
        suffix: str = "%",
    ) -> list[str]:
        """Labelled horizontal bars, used for the Vibe Vector."""
        return [
            f"    {name[:label_width]:<{label_width}} "
            f"{self.gauge(value, width=width, maximum=maximum, rgb=ACCENT)} "
            f"{value:5.0f}{suffix}"
            for name, value in items
        ]

    # -- animation ---------------------------------------------------------

    def _writable(self) -> bool:
        return self.caps.animate and self.caps.colour

    def reveal_gauge(
        self,
        label: str,
        value: float,
        weight: float,
        detail: str = "",
        *,
        width: int = 24,
        duration: float = 0.35,
    ) -> None:
        """Animate one score axis filling, then leave the final line in place.

        Falls back to printing the finished line when animation is unavailable,
        so a piped run produces exactly the same final output.
        """
        final = self.axis_row(label, value, weight, detail, width=width)
        if not self._writable():
            self.stream.write(final + "\n")
            return

        steps = max(1, int(width * max(0.0, min(1.0, value / 100.0))))
        delay = duration / steps
        self.stream.write("\033[?25l")
        try:
            for step in range(1, steps + 1):
                partial = value * step / steps
                self.stream.write("\r" + self.axis_row(label, partial, weight, width=width))
                self.stream.flush()
                time.sleep(delay)
            self.stream.write("\r" + final + "\n")
        finally:
            self.stream.write("\033[?25h")
            self.stream.flush()

    def typewriter(self, text: str, *, delay: float = 0.012) -> None:
        if not self._writable():
            self.stream.write(text + "\n")
            return
        for char in text:
            self.stream.write(char)
            self.stream.flush()
            time.sleep(delay)
        self.stream.write("\n")

    def star_burst(self, count: int, *, delay: float = 0.16) -> None:
        """Reveal earned stars one at a time. Pure ceremony, and worth it."""
        if not self._writable():
            self.stream.write("    " + self.stars(count) + "\n")
            return
        self.stream.write("    ")
        for index in range(3):
            self.stream.write(
                self.paint(self.glyph("star_full"), GOLD)
                if index < count
                else self.paint(self.glyph("star_empty"), FAINT)
            )
            self.stream.flush()
            time.sleep(delay)
        self.stream.write("\n")

    def write(self, *lines: str) -> None:
        for line in lines:
            self.stream.write(line + "\n")


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

def strip_ansi(text: str) -> str:
    """Remove every escape sequence. Used by tests to compare visible output."""
    out: list[str] = []
    index = 0
    while index < len(text):
        if text[index] == "\033":
            terminator = text.find("m", index)
            if terminator == -1:
                break
            index = terminator + 1
            continue
        out.append(text[index])
        index += 1
    return "".join(out)


def visible_width(text: str) -> int:
    return len(strip_ansi(text))


def renderer_for(stream=None) -> Renderer:
    stream = stream or sys.stdout
    return Renderer(detect(stream), stream)


def wrap(text: str, width: int, indent: str = "  ") -> Iterable[str]:
    """Greedy word wrap. Used for level briefs, which are prose."""
    words, line = text.split(), ""
    for word in words:
        candidate = f"{line} {word}".strip()
        if len(candidate) + len(indent) > width and line:
            yield indent + line
            line = word
        else:
            line = candidate
    if line:
        yield indent + line
