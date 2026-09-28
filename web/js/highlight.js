// Python syntax colour that survives incomplete input.
//
// The same rule `vibecoder/highlight.py` follows for the terminal: a player is
// always mid-edit, so an unterminated string or a half-typed keyword must
// colour sensibly rather than throw. Triple-quoted strings carry state from
// one line to the next; nothing else does.

import { esc } from "./dom.js";

const KEYWORDS = new Set((
  "and as assert async await break class continue def del elif else except " +
  "finally for from global if import in is lambda nonlocal not or pass raise " +
  "return try while with yield match case"
).split(" "));
const CONSTANTS = new Set(["True", "False", "None"]);
const BUILTINS = new Set((
  "abs all any bool dict enumerate filter float frozenset getattr hasattr int " +
  "isinstance iter len list map max min next object print range repr reversed " +
  "round set sorted str sum super tuple type zip divmod ord chr hash id input " +
  "open format slice callable issubclass pow bin hex oct vars dir Exception " +
  "ValueError TypeError KeyError IndexError ZeroDivisionError StopIteration " +
  "RuntimeError AttributeError NotImplementedError"
).split(" "));

const TOKEN = new RegExp([
  "(#.*)",                                                        // 1 comment
  "([rRbBuUfF]{0,2}(?:\"\"\"|'''))",                              // 2 triple open
  "([rRbBuUfF]{0,2}(?:\"(?:[^\"\\\\\\n]|\\\\.)*\"?|'(?:[^'\\\\\\n]|\\\\.)*'?))", // 3 string
  "(\\b(?:0[xXoObB][0-9a-fA-F_]+|\\d[\\d_]*\\.?\\d*(?:[eE][+-]?\\d+)?j?|\\.\\d+)\\b)", // 4 number
  "(@[A-Za-z_][\\w.]*)",                                          // 5 decorator
  "([A-Za-z_][A-Za-z0-9_]*)",                                     // 6 name
  "([-+*/%=<>!&|^~:.,;()\\[\\]{}]+)",                             // 7 operator
].join("|"), "g");

function span(kind, text) {
  return `<span class="t-${kind}">${esc(text)}</span>`;
}

// Returns one HTML string per line.
export function highlight(source) {
  const out = [];
  let open = null; // the quote of an unterminated triple string
  let previousWord = "";
  for (const line of source.split("\n")) {
    let html = "";
    let at = 0;
    if (open) {
      const end = line.indexOf(open);
      if (end === -1) { out.push(span("str", line)); continue; }
      html += span("str", line.slice(0, end + 3));
      at = end + 3;
      open = null;
    }
    TOKEN.lastIndex = at;
    let match;
    while ((match = TOKEN.exec(line)) !== null) {
      if (match.index > at) html += esc(line.slice(at, match.index));
      const [text, comment, triple, string, number, decorator, name, operator] = match;
      if (comment) html += span("com", comment);
      else if (triple) {
        const quote = triple.slice(-3);
        const close = line.indexOf(quote, match.index + triple.length);
        if (close === -1) {
          html += span("str", line.slice(match.index));
          open = quote;
          TOKEN.lastIndex = line.length;
          at = line.length;
          break;
        }
        html += span("str", line.slice(match.index, close + 3));
        TOKEN.lastIndex = close + 3;
        at = close + 3;
        continue;
      } else if (string) html += span("str", string);
      else if (number) html += span("num", number);
      else if (decorator) html += span("dec", decorator);
      else if (name) {
        if (previousWord === "def" || previousWord === "class") html += span("def", name);
        else if (KEYWORDS.has(name)) html += span("kw", name);
        else if (CONSTANTS.has(name)) html += span("const", name);
        else if (name === "self") html += span("self", name);
        else if (BUILTINS.has(name)) html += span("bi", name);
        else html += esc(name);
        previousWord = name;
        at = TOKEN.lastIndex;
        continue;
      } else if (operator) html += span("op", operator);
      else html += esc(text);
      previousWord = "";
      at = TOKEN.lastIndex;
      if (text.length === 0) TOKEN.lastIndex += 1;
    }
    if (at < line.length) html += esc(line.slice(at));
    out.push(html);
  }
  return out;
}
