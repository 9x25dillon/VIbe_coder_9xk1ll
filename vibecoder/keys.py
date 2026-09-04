"""Decode terminal input into key events. T7 W2.

A terminal does not deliver keys, it delivers bytes, and it delivers them
whenever it feels like it. Pressing Up may arrive as ``\\x1b[A`` in one read or
as ``\\x1b`` then ``[A`` across two, and a pasted line arrives as a hundred
bytes with no keystrokes in it at all. So this is a state machine that is fed
bytes and yields whatever complete keys those bytes completed -- never a
lookup table, which is the shape that works until someone pastes something or
presses Escape.

Decoding runs on *characters*, not bytes: an incremental UTF-8 decoder sits in
front, so a multi-byte character split across two reads is the decoder's
problem rather than the state machine's. Every escape sequence is ASCII, so
nothing is lost by looking at text.
"""

from __future__ import annotations

import codecs
import time
from dataclasses import dataclass

ESC = "\x1b"

#: How long a held Escape waits for the rest of a sequence before it is taken
#: to be a bare Escape keypress. Terminals send `ESC [ A` as three bytes with
#: no delay between them, so anything arriving later than this really was a
#: person pressing Escape. Too short and a sequence split across a slow link
#: gets torn apart and typed as text; too long and Escape feels sticky.
ESCAPE_TIMEOUT = 0.05

#: Final byte of a CSI sequence -> key name, for the sequences that carry no
#: numeric parameter.
CSI_LETTERS = {
    "A": "up", "B": "down", "C": "right", "D": "left",
    "H": "home", "F": "end",
    "Z": "backtab",
}

#: `ESC [ <n> ~` sequences.
CSI_TILDE = {
    "1": "home", "2": "insert", "3": "delete", "4": "end",
    "5": "pgup", "6": "pgdn", "7": "home", "8": "end",
}

PASTE_START = "200"
PASTE_END = "201"


@dataclass(frozen=True)
class Key:
    """One key press, or one paste.

    ``name`` is ``"char"`` for ordinary text, ``"paste"`` for a bracketed
    paste, and otherwise the name of a special key. Comparing against
    ``Key.printable`` is usually better than testing ``name`` directly.
    """

    name: str
    char: str = ""
    ctrl: bool = False
    alt: bool = False
    text: str = ""

    @property
    def printable(self) -> bool:
        return self.name == "char" and not self.ctrl and not self.alt

    def __str__(self) -> str:
        if self.printable:
            return self.char
        parts = []
        if self.ctrl:
            parts.append("ctrl")
        if self.alt:
            parts.append("alt")
        parts.append(self.char or self.name)
        return "-".join(parts)


def _control(char: str) -> Key:
    """Map a C0 control character to the key that produced it."""
    code = ord(char)
    if char in ("\r", "\n"):
        return Key("enter")
    if char == "\t":
        return Key("tab")
    if char in ("\x7f", "\x08"):
        return Key("backspace")
    # ^A is 0x01, and 0x01 + 96 is 'a'. ^@ (NUL) has no letter, so it is named.
    if code == 0:
        return Key("char", " ", ctrl=True)
    return Key("char", chr(code + 96), ctrl=True)


class KeyDecoder:
    """Feed it bytes, take complete keys out.

    Incomplete input is held rather than guessed at, so a sequence split
    across reads decodes correctly on the read that finishes it.
    """

    def __init__(self, escape_timeout: float = ESCAPE_TIMEOUT) -> None:
        self._decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        self._pending = ""
        self._paste: list[str] | None = None
        self._escape_timeout = escape_timeout
        self._held_since = 0.0

    def feed(self, data: bytes, now: float | None = None) -> list[Key]:
        if data:
            self._held_since = time.monotonic() if now is None else now
        self._pending += self._decoder.decode(data)
        keys: list[Key] = []
        while self._pending:
            key, consumed = self._step(self._pending)
            if consumed == 0:
                break  # incomplete; wait for more bytes
            self._pending = self._pending[consumed:]
            if key is not None:
                keys.append(key)
        return keys

    def flush(self, now: float | None = None) -> list[Key]:
        """Resolve input held because it might have been a longer sequence.

        Safe to call on every idle tick: held input is only resolved once it
        has sat untouched for ``escape_timeout``. That patience is the whole
        point. An editor that redraws every 50 ms calls this constantly, and
        resolving eagerly would tear apart any sequence whose bytes happened
        to straddle a tick -- emitting Escape and then typing ``[A`` as text,
        which is what a slow ssh link produces on every arrow key.
        """
        if not self._pending:
            return []
        now = time.monotonic() if now is None else now
        if now - self._held_since < self._escape_timeout:
            return []  # the rest of the sequence may still be in flight
        if self._pending == ESC:
            self._pending = ""
            return [Key("escape")]
        if self._pending[0] == ESC:
            # A sequence that started and then genuinely stopped. Drop it
            # rather than emitting its bytes as text.
            self._pending = ""
            return []
        return self.feed(b"", now=now)

    # -- the machine -------------------------------------------------------

    def _step(self, text: str) -> tuple[Key | None, int]:
        """Decode one key from the front of ``text``.

        Returns the key (or None when the input was consumed without
        producing one) and how many characters it used. A zero means the input
        is a valid prefix of something longer.
        """
        if self._paste is not None:
            return self._step_paste(text)

        first = text[0]
        if first != ESC:
            if ord(first) < 0x20 or first == "\x7f":
                return _control(first), 1
            return Key("char", first), 1

        if len(text) == 1:
            return None, 0  # bare ESC, or the start of a sequence
        second = text[1]

        if second == "[":
            return self._step_csi(text)
        if second == "O":
            # SS3: arrows in application cursor mode.
            if len(text) < 3:
                return None, 0
            name = CSI_LETTERS.get(text[2])
            return (Key(name) if name else None), 3
        if second == ESC:
            # ESC ESC: an Escape press followed by another sequence.
            return Key("escape"), 1
        if ord(second) < 0x20:
            key = _control(second)
            return Key(key.name, key.char, ctrl=key.ctrl, alt=True), 2
        return Key("char", second, alt=True), 2

    def _step_csi(self, text: str) -> tuple[Key | None, int]:
        index = 2
        while index < len(text) and (text[index].isdigit() or text[index] == ";"):
            index += 1
        if index >= len(text):
            return None, 0  # parameters still arriving
        final = text[index]
        params = text[2:index]
        consumed = index + 1

        if final == "~":
            head = params.split(";")[0]
            if head == PASTE_START:
                self._paste = []
                return None, consumed
            name = CSI_TILDE.get(head)
            return (Key(name) if name else None), consumed

        name = CSI_LETTERS.get(final)
        if name is None:
            return None, consumed  # a sequence we do not model; discard it
        # `ESC [ 1 ; 5 A` is ctrl-Up. Modifier is a bitfield offset by one.
        modifier = 0
        if ";" in params:
            try:
                modifier = int(params.split(";")[1]) - 1
            except ValueError:
                modifier = 0
        return Key(name, ctrl=bool(modifier & 4), alt=bool(modifier & 2)), consumed

    def _step_paste(self, text: str) -> tuple[Key | None, int]:
        """Inside a bracketed paste: everything is literal until the end mark."""
        assert self._paste is not None
        end = f"{ESC}[{PASTE_END}~"
        position = text.find(end)
        if position == -1:
            # Hold back anything that could be the start of the end marker.
            safe = len(text)
            for length in range(1, min(len(end), len(text)) + 1):
                if text.endswith(end[:length]):
                    safe = len(text) - length
                    break
            if safe == 0:
                return None, 0
            self._paste.append(text[:safe])
            return None, safe
        self._paste.append(text[:position])
        pasted = "".join(self._paste)
        self._paste = None
        return Key("paste", text=pasted), position + len(end)
