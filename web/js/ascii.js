// Everything drawn with characters: the logo, the bosses, the bars.
//
// Glyphs are assembled from per-letter arrays and padded here, rather than
// typed as one block, because a single misaligned column in hand-typed art is
// invisible in source and obvious on a screen.

import { html, raw } from "./dom.js";

const LETTERS = {
  V: ["██╗   ██╗", "██║   ██║", "██║   ██║", "╚██╗ ██╔╝", " ╚████╔╝ ", "  ╚═══╝  "],
  I: ["██╗", "██║", "██║", "██║", "██║", "╚═╝"],
  B: ["██████╗ ", "██╔══██╗", "██████╔╝", "██╔══██╗", "██████╔╝", "╚═════╝ "],
  E: ["███████╗", "██╔════╝", "█████╗  ", "██╔══╝  ", "███████╗", "╚══════╝"],
  C: [" ██████╗", "██╔════╝", "██║     ", "██║     ", "╚██████╗", " ╚═════╝"],
  O: [" ██████╗ ", "██╔═══██╗", "██║   ██║", "██║   ██║", "╚██████╔╝", " ╚═════╝ "],
  D: ["██████╗ ", "██╔══██╗", "██║  ██║", "██║  ██║", "██████╔╝", "╚═════╝ "],
  R: ["██████╗ ", "██╔══██╗", "██████╔╝", "██╔══██╗", "██║  ██║", "╚═╝  ╚═╝"],
};

export function banner(word) {
  const rows = ["", "", "", "", "", ""];
  for (const letter of word) {
    const glyph = LETTERS[letter];
    const width = Math.max(...glyph.map((line) => [...line].length));
    glyph.forEach((line, i) => { rows[i] += line.padEnd(width, " "); });
  }
  return rows.join("\n");
}

// Stacked on a phone, one line on anything wider: the stacked version can be
// drawn half again as large in the same width.
export function logo(width) {
  const text = width < 560 ? `${banner("VIBE")}\n${banner("CODER")}` : banner("VIBECODER");
  const columns = Math.max(...text.split("\n").map((line) => [...line].length));
  // JetBrains Mono advances 0.6em per glyph.
  const size = Math.max(6, Math.min(width < 560 ? 17 : 15, (width - 32) / columns / 0.6));
  return html`<pre class="logo glitch" style="font-size:${size.toFixed(2)}px" data-text="${text}" aria-label="VibeCoder">${text}</pre>`;
}

export const BOSSES = {
  "w1-boss-pipeline": [
    "      ▄▄████████████▄▄      ",
    "   ▄██▀▀  ▄▄    ▄▄  ▀▀██▄   ",
    "  ██▀   ▄████▄▄████▄   ▀██  ",
    " ██▀    ██◉ ██ ██ ◉██    ▀██ ",
    " ██     ▀████▀▀████▀     ██ ",
    " ▀██▄      ▄▄▄▄▄▄      ▄██▀ ",
    "   ▀██▄   █▀▀▀▀▀▀█   ▄██▀   ",
    "     ▀████ ▀▀▀▀▀▀ ████▀     ",
    "  ═╦═══╩══╦══════╦══╩═══╦═  ",
    "   ║      ║ FEED ║      ║   ",
    "  ═╩══════╩══════╩══════╩═  ",
  ],
  "w2-boss-ledger": [
    "   ╔══════════════════════╗   ",
    "   ║ ▓▓  L E D G E R  ▓▓ ║   ",
    "   ╠══════════════════════╣   ",
    "   ║   ▄███▄      ▄███▄   ║   ",
    "   ║   █ $ █      █ $ █   ║   ",
    "   ║   ▀███▀  ▄▄  ▀███▀   ║   ",
    "   ║  ▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄  ║   ",
    "   ║  █▀█▀█▀█▀█▀█▀█▀█▀█▀  ║   ",
    "   ║  ▀ ▀ ▀ ▀ ▀ ▀ ▀ ▀ ▀   ║   ",
    "   ╚═══╦══════════════╦═══╝   ",
    "      ═╩═            ═╩═      ",
  ],
};

const FALLBACK = [
  "    ▄▄▄████▄▄▄    ",
  "  ▄██▀▀    ▀▀██▄  ",
  " ██  ▄█▄  ▄█▄  ██ ",
  " ██  ▀█▀  ▀█▀  ██ ",
  "  ▀██▄  ▀▀  ▄██▀  ",
  "    ▀▀██████▀▀    ",
];

export function bossArt(id) {
  return (BOSSES[id] || FALLBACK).join("\n");
}

// A text bar: `███████░░░░` with the empty part dimmed. Fractional cells use
// the eighth-blocks so a 97 and a 100 look different at twelve cells.
const EIGHTHS = ["", "▏", "▎", "▍", "▌", "▋", "▊", "▉"];

export function bar(value, max, cells = 20) {
  const ratio = Math.max(0, Math.min(1, max ? value / max : 0));
  const exact = ratio * cells;
  const full = Math.floor(exact);
  const part = EIGHTHS[Math.round((exact - full) * 8)] || "";
  const filled = "█".repeat(full) + (full < cells ? part : "");
  const empty = "░".repeat(Math.max(0, cells - [...filled].length));
  return html`${filled}<span class="empty">${empty}</span>`;
}

export function stars(count, total = 3) {
  const on = "★".repeat(count);
  const off = "☆".repeat(Math.max(0, total - count));
  return html`<span class="stars" aria-label="${count} of ${total} stars">${on}<span class="off">${off}</span></span>`;
}

export function pips(left, spent) {
  return html`<span class="pips" aria-label="${left} repairs left">${"◆".repeat(left)}<span class="spent">${"◇".repeat(spent)}</span></span>`;
}

export { raw };
