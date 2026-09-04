"""Key decoding. The cases that matter are the ones split across reads."""

import unittest

from vibecoder.keys import Key, KeyDecoder


class TestPrintable(unittest.TestCase):
    def test_ascii_characters_decode_one_by_one(self):
        keys = KeyDecoder().feed(b"abc")
        self.assertEqual([k.char for k in keys], ["a", "b", "c"])
        self.assertTrue(all(k.printable for k in keys))

    def test_a_multibyte_character_split_across_reads(self):
        """The read boundary is not the decoder's business."""
        d = KeyDecoder()
        raw = "é".encode()
        self.assertEqual(d.feed(raw[:1]), [])
        self.assertEqual([k.char for k in d.feed(raw[1:])], ["é"])

    def test_invalid_utf8_does_not_raise(self):
        self.assertIsInstance(KeyDecoder().feed(b"\xff\xfe"), list)


class TestControl(unittest.TestCase):
    def test_carriage_return_and_newline_are_both_enter(self):
        self.assertEqual(KeyDecoder().feed(b"\r")[0].name, "enter")
        self.assertEqual(KeyDecoder().feed(b"\n")[0].name, "enter")

    def test_tab_and_backspace(self):
        self.assertEqual(KeyDecoder().feed(b"\t")[0].name, "tab")
        self.assertEqual(KeyDecoder().feed(b"\x7f")[0].name, "backspace")

    def test_ctrl_letters_carry_the_letter(self):
        key = KeyDecoder().feed(b"\x03")[0]
        self.assertTrue(key.ctrl)
        self.assertEqual(key.char, "c")
        self.assertFalse(key.printable)

    def test_a_control_key_is_never_printable(self):
        for raw in (b"\x01", b"\r", b"\t", b"\x7f"):
            self.assertFalse(KeyDecoder().feed(raw)[0].printable, raw)


class TestSequences(unittest.TestCase):
    def test_arrows(self):
        names = [k.name for k in KeyDecoder().feed(b"\x1b[A\x1b[B\x1b[C\x1b[D")]
        self.assertEqual(names, ["up", "down", "right", "left"])

    def test_an_arrow_split_across_two_reads(self):
        d = KeyDecoder()
        self.assertEqual(d.feed(b"\x1b"), [])
        self.assertEqual([k.name for k in d.feed(b"[A")], ["up"])

    def test_an_arrow_split_after_the_bracket(self):
        d = KeyDecoder()
        self.assertEqual(d.feed(b"\x1b["), [])
        self.assertEqual([k.name for k in d.feed(b"A")], ["up"])

    def test_application_cursor_mode_arrows(self):
        self.assertEqual([k.name for k in KeyDecoder().feed(b"\x1bOA")], ["up"])

    def test_home_end_delete_and_paging(self):
        raw = b"\x1b[H\x1b[F\x1b[3~\x1b[5~\x1b[6~"
        names = [k.name for k in KeyDecoder().feed(raw)]
        self.assertEqual(names, ["home", "end", "delete", "pgup", "pgdn"])

    def test_a_modified_arrow_reports_the_modifier(self):
        key = KeyDecoder().feed(b"\x1b[1;5A")[0]
        self.assertEqual(key.name, "up")
        self.assertTrue(key.ctrl)

    def test_an_unmodelled_sequence_is_discarded_not_typed(self):
        """The failure to avoid is emitting the escape bytes as text."""
        self.assertEqual(KeyDecoder().feed(b"\x1b[999X"), [])

    def test_alt_plus_a_letter(self):
        key = KeyDecoder().feed(b"\x1ba")[0]
        self.assertTrue(key.alt)
        self.assertEqual(key.char, "a")


class TestEscape(unittest.TestCase):
    """Escape and the first byte of a sequence are the same byte.

    Telling them apart is a question of time, so these tests supply it
    explicitly rather than sleeping.
    """

    def test_a_lone_escape_resolves_once_the_timeout_passes(self):
        d = KeyDecoder(escape_timeout=0.05)
        self.assertEqual(d.feed(b"\x1b", now=100.0), [])
        self.assertEqual([k.name for k in d.flush(now=100.2)], ["escape"])

    def test_a_lone_escape_is_still_held_before_the_timeout(self):
        d = KeyDecoder(escape_timeout=0.05)
        d.feed(b"\x1b", now=100.0)
        self.assertEqual(d.flush(now=100.01), [])

    def test_a_sequence_split_across_an_idle_tick_is_not_torn_apart(self):
        """The bug this timeout exists for.

        A redraw loop calls flush() on every idle tick. Resolving eagerly
        turned `ESC [ Z` arriving in three reads into Escape followed by the
        literal characters "[Z", which the editor then typed into the buffer.
        Over a slow link that happened on every arrow key.
        """
        d = KeyDecoder(escape_timeout=0.05)
        self.assertEqual(d.feed(b"\x1b", now=100.000), [])
        self.assertEqual(d.flush(now=100.010), [])   # idle tick mid-sequence
        self.assertEqual(d.feed(b"[", now=100.020), [])
        self.assertEqual(d.flush(now=100.030), [])   # and another
        keys = d.feed(b"Z", now=100.040)
        self.assertEqual([k.name for k in keys], ["backtab"])

    def test_an_arrow_split_across_idle_ticks_still_decodes(self):
        d = KeyDecoder(escape_timeout=0.05)
        d.feed(b"\x1b", now=100.0)
        d.flush(now=100.01)
        d.feed(b"[", now=100.02)
        d.flush(now=100.03)
        self.assertEqual([k.name for k in d.feed(b"A", now=100.04)], ["up"])

    def test_an_abandoned_sequence_is_dropped_not_typed(self):
        d = KeyDecoder(escape_timeout=0.05)
        d.feed(b"\x1b[", now=100.0)
        self.assertEqual(d.flush(now=100.5), [])
        # And the decoder is usable afterwards.
        self.assertEqual([k.char for k in d.feed(b"x", now=100.6)], ["x"])

    def test_flushing_an_empty_decoder_does_nothing(self):
        self.assertEqual(KeyDecoder().flush(now=100.0), [])


class TestPaste(unittest.TestCase):
    def test_a_bracketed_paste_arrives_as_one_key(self):
        keys = KeyDecoder().feed(b"\x1b[200~x = 1\ny = 2\x1b[201~")
        self.assertEqual(len(keys), 1)
        self.assertEqual(keys[0].name, "paste")
        self.assertEqual(keys[0].text, "x = 1\ny = 2")

    def test_a_paste_split_across_reads_reassembles(self):
        d = KeyDecoder()
        self.assertEqual(d.feed(b"\x1b[200~hel"), [])
        self.assertEqual(d.feed(b"lo\x1b[201~")[0].text, "hello")

    def test_a_paste_split_inside_the_end_marker_reassembles(self):
        """The nastiest split: the terminator itself straddles a read."""
        d = KeyDecoder()
        d.feed(b"\x1b[200~hello\x1b[20")
        keys = d.feed(b"1~")
        self.assertEqual(keys[0].text, "hello")

    def test_control_characters_inside_a_paste_stay_literal(self):
        keys = KeyDecoder().feed(b"\x1b[200~a\tb\x1b[201~")
        self.assertEqual(keys[0].text, "a\tb")

    def test_typing_resumes_after_a_paste(self):
        keys = KeyDecoder().feed(b"\x1b[200~x\x1b[201~y")
        self.assertEqual([k.name for k in keys], ["paste", "char"])


class TestKeyRepr(unittest.TestCase):
    def test_a_printable_key_stringifies_as_itself(self):
        self.assertEqual(str(Key("char", "a")), "a")

    def test_a_control_key_stringifies_readably(self):
        self.assertEqual(str(Key("char", "r", ctrl=True)), "ctrl-r")
        self.assertEqual(str(Key("up")), "up")


if __name__ == "__main__":
    unittest.main()
