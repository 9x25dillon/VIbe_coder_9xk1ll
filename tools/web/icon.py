"""The app icon, drawn once as a pixel map and exported to every format.

One 16x16 map is the source of truth for the favicon (SVG), the installable
web app (PNG), and the Android launcher (an adaptive-icon vector drawable), so
the three cannot drift into three different logos. Pixel art is also the only
kind of art that survives being written as a grid in a Python file.

Stdlib only: PNGs are written by hand with `zlib`.
"""

from __future__ import annotations

import struct
import zlib
from pathlib import Path

#: A = acid, P = pink glitch ghost, C = cursor. Everything else is background.
ART = [
    "................",
    "................",
    "..AA........AA..",
    "..AAP.......AAP.",
    "..AAP.......AAP.",
    "...AAP.....AAP..",
    "...AAP.....AAP..",
    "....AAP...AAP...",
    "....AAP...AAP...",
    ".....AAP.AAP....",
    ".....AAP.AAP....",
    "......AAAAP.....",
    "......AAAAP.CC..",
    ".......AAP..CC..",
    "................",
    "................",
]

COLOURS = {"A": "#b6ff00", "P": "#ff2e97", "C": "#00e8ff"}
BACKGROUND = "#050507"


def _rgb(hex_colour: str) -> tuple[int, int, int]:
    value = hex_colour.lstrip("#")
    return int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)


def cells():
    for y, row in enumerate(ART):
        for x, char in enumerate(row):
            if char in COLOURS:
                yield x, y, COLOURS[char]


def svg() -> str:
    rects = "".join(
        f'<rect x="{x}" y="{y}" width="1.02" height="1.02" fill="{colour}"/>'
        for x, y, colour in cells()
    )
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16" '
        'shape-rendering="crispEdges">'
        f'<rect width="16" height="16" rx="2" fill="{BACKGROUND}"/>{rects}</svg>\n'
    )


def png(size: int, *, padding: float = 0.0) -> bytes:
    """A square PNG. ``padding`` is the fraction of the edge left empty on
    each side, which is what a maskable icon's safe zone needs."""
    grid = len(ART)
    inner = size * (1 - 2 * padding)
    cell = inner / grid
    offset = size * padding
    background = _rgb(BACKGROUND)
    pixels = [[background] * size for _ in range(size)]
    for x, y, colour in cells():
        rgb = _rgb(colour)
        for py in range(int(offset + y * cell), int(offset + (y + 1) * cell)):
            for px in range(int(offset + x * cell), int(offset + (x + 1) * cell)):
                pixels[py][px] = rgb
    raw = b"".join(b"\x00" + bytes(c for rgb in row for c in rgb) for row in pixels)

    def chunk(kind: bytes, data: bytes) -> bytes:
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

    header = struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header)
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def android_foreground() -> str:
    """Adaptive-icon foreground: 108dp canvas, art inside the 66dp safe zone."""
    scale, origin = 4, (108 - 16 * 4) / 2
    paths = []
    for colour in COLOURS.values():
        data = "".join(
            f"M{origin + x * scale:g},{origin + y * scale:g}h{scale}v{scale}h-{scale}z"
            for x, y, c in cells() if c == colour
        )
        if data:
            paths.append(f'  <path android:fillColor="{colour}" android:pathData="{data}"/>')
    return (
        '<vector xmlns:android="http://schemas.android.com/apk/res/android"\n'
        '    android:width="108dp" android:height="108dp"\n'
        '    android:viewportWidth="108" android:viewportHeight="108">\n'
        + "\n".join(paths) + "\n</vector>\n"
    )


def android_monochrome() -> str:
    """Themed-icon layer: the same shape, one colour, tinted by the launcher."""
    scale, origin = 4, (108 - 16 * 4) / 2
    data = "".join(
        f"M{origin + x * scale:g},{origin + y * scale:g}h{scale}v{scale}h-{scale}z"
        for x, y, c in cells() if c != COLOURS["P"]
    )
    return (
        '<vector xmlns:android="http://schemas.android.com/apk/res/android"\n'
        '    android:width="108dp" android:height="108dp"\n'
        '    android:viewportWidth="108" android:viewportHeight="108">\n'
        f'  <path android:fillColor="#FFFFFFFF" android:pathData="{data}"/>\n</vector>\n'
    )


def write_web(directory: Path) -> None:
    (directory / "icon.svg").write_text(svg())
    (directory / "icon-192.png").write_bytes(png(192))
    (directory / "icon-512.png").write_bytes(png(512))
    (directory / "icon-maskable-512.png").write_bytes(png(512, padding=0.14))
