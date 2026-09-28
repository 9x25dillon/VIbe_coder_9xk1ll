// A code editor made of a textarea and a highlighted mirror.
//
// The textarea owns the text, the caret, selection, IME and native undo; the
// `<pre>` behind it only paints. Every edit made on the player's behalf goes
// through `insertText`, so undo stays the browser's own and the phone's
// keyboard never loses its place. No framework and no editor library: the
// whole thing has to load offline inside an APK.

import { highlight } from "./highlight.js";

const INDENT = "    ";

export class CodeEditor {
  constructor(root, { value = "", readOnly = false, onRun = null, label = "code editor" } = {}) {
    this.root = root;
    this.onRun = onRun;
    root.classList.add("ed");
    root.classList.toggle("readonly", readOnly);
    root.innerHTML = `
      <div class="ed-gutter" aria-hidden="true"></div>
      <div class="ed-body">
        <div class="ed-marks" aria-hidden="true"></div>
        <pre class="ed-hl" aria-hidden="true"></pre>
        <textarea class="ed-src" spellcheck="false" autocapitalize="off"
          autocomplete="off" autocorrect="off" wrap="off" enterkeyhint="enter"></textarea>
      </div>`;
    this.gutter = root.querySelector(".ed-gutter");
    this.marks = root.querySelector(".ed-marks");
    this.mirror = root.querySelector(".ed-hl");
    this.text = root.querySelector(".ed-src");
    this.text.setAttribute("aria-label", label);
    this.text.readOnly = readOnly;
    this.text.value = value;
    this.lineMarks = new Map();
    this.pending = 0;
    this.text.addEventListener("input", () => this.schedule());
    this.text.addEventListener("scroll", () => this.follow());
    this.text.addEventListener("keydown", (event) => this.key(event));
    this.paint();
  }

  get value() { return this.text.value; }

  set value(text) {
    this.text.value = text;
    this.paint();
  }

  focus() { this.text.focus({ preventScroll: true }); }

  schedule() {
    if (this.pending) return;
    this.pending = requestAnimationFrame(() => { this.pending = 0; this.paint(); });
  }

  paint() {
    const lines = highlight(this.text.value);
    this.mirror.innerHTML = lines.join("\n") + "\n";
    const gutter = [];
    for (let i = 1; i <= lines.length; i += 1) {
      const mark = this.lineMarks.get(i);
      gutter.push(`<div class="${mark || ""}">${i}</div>`);
    }
    this.gutter.innerHTML = gutter.join("");
    this.drawMarks();
    this.follow();
  }

  follow() {
    const x = this.text.scrollLeft;
    const y = this.text.scrollTop;
    this.mirror.style.transform = `translate(${-x}px, ${-y}px)`;
    this.marks.style.transform = `translateY(${-y}px)`;
    this.gutter.scrollTop = y;
  }

  // Mark a line as the current execution point ("cur") or a failure ("err").
  mark(line, kind) {
    for (const [key, value] of [...this.lineMarks]) if (value === kind) this.lineMarks.delete(key);
    if (line) this.lineMarks.set(line, kind);
    this.paint();
    if (line) this.reveal(line);
  }

  clearMarks() {
    this.lineMarks.clear();
    this.paint();
  }

  drawMarks() {
    const height = parseFloat(getComputedStyle(this.text).lineHeight) || 21;
    const top = parseFloat(getComputedStyle(this.text).paddingTop) || 10;
    this.marks.innerHTML = [...this.lineMarks]
      .map(([line, kind]) => `<div class="line-mark ${kind}" style="top:${top + (line - 1) * height}px"></div>`)
      .join("");
  }

  reveal(line) {
    const height = parseFloat(getComputedStyle(this.text).lineHeight) || 21;
    const y = (line - 1) * height;
    const view = this.text.clientHeight;
    if (y < this.text.scrollTop + height || y > this.text.scrollTop + view - height * 3) {
      this.text.scrollTop = Math.max(0, y - view / 3);
    }
  }

  moveCaretToLine(line) {
    const lines = this.text.value.split("\n");
    let offset = 0;
    for (let i = 0; i < Math.min(line - 1, lines.length); i += 1) offset += lines[i].length + 1;
    const indent = (lines[line - 1] || "").match(/^\s*/)[0].length;
    this.text.setSelectionRange(offset + indent, offset + (lines[line - 1] || "").length);
    this.reveal(line);
  }

  // Insert text at the caret, keeping it on the browser's undo stack.
  insert(text) {
    this.text.focus({ preventScroll: true });
    if (!document.execCommand("insertText", false, text)) {
      this.text.setRangeText(text, this.text.selectionStart, this.text.selectionEnd, "end");
      this.text.dispatchEvent(new Event("input"));
    }
  }

  lineBounds() {
    const value = this.text.value;
    const start = value.lastIndexOf("\n", this.text.selectionStart - 1) + 1;
    let end = value.indexOf("\n", this.text.selectionEnd);
    if (end === -1) end = value.length;
    return { start, end };
  }

  indent() {
    const { selectionStart, selectionEnd } = this.text;
    if (selectionStart === selectionEnd) { this.insert(INDENT); return; }
    const { start, end } = this.lineBounds();
    const block = this.text.value.slice(start, end);
    this.text.setSelectionRange(start, end);
    this.insert(block.split("\n").map((line) => INDENT + line).join("\n"));
    this.text.setSelectionRange(start, start + block.length + INDENT.length * block.split("\n").length);
  }

  dedent() {
    const { start, end } = this.lineBounds();
    const block = this.text.value.slice(start, end);
    const changed = block.split("\n").map((line) => line.replace(/^ {1,4}/, "")).join("\n");
    if (changed === block) return;
    this.text.setSelectionRange(start, end);
    this.insert(changed);
    this.text.setSelectionRange(start, start + changed.length);
  }

  newline() {
    const value = this.text.value;
    const caret = this.text.selectionStart;
    const lineStart = value.lastIndexOf("\n", caret - 1) + 1;
    const before = value.slice(lineStart, caret);
    let indent = before.match(/^\s*/)[0];
    if (/:\s*(#.*)?$/.test(before)) indent += INDENT;
    else if (/^\s*(return|pass|break|continue|raise)\b/.test(before)) indent = indent.slice(0, Math.max(0, indent.length - 4));
    this.insert("\n" + indent);
  }

  backspace(event) {
    const { selectionStart, selectionEnd, value } = this.text;
    if (selectionStart !== selectionEnd) return;
    const lineStart = value.lastIndexOf("\n", selectionStart - 1) + 1;
    const before = value.slice(lineStart, selectionStart);
    if (before.length && /^ +$/.test(before)) {
      event.preventDefault();
      const remove = before.length % 4 || 4;
      this.text.setSelectionRange(selectionStart - remove, selectionStart);
      this.insert("");
    }
  }

  key(event) {
    if (this.text.readOnly) return;
    if ((event.ctrlKey || event.metaKey) && event.key === "Enter") {
      event.preventDefault();
      if (this.onRun) this.onRun();
      return;
    }
    if (event.key === "Tab") {
      event.preventDefault();
      if (event.shiftKey) this.dedent(); else this.indent();
    } else if (event.key === "Enter" && !event.isComposing) {
      event.preventDefault();
      this.newline();
    } else if (event.key === "Backspace") {
      this.backspace(event);
    }
  }
}

// The symbols a phone keyboard hides two layers deep, one tap away. Buttons
// act on pointerdown and cancel it, so the textarea keeps focus and the
// keyboard stays up.
const KEYS = [
  ["⇥", "indent", "k-wide"], ["⇤", "dedent", "k-wide"],
  ["(", "()"], [")", ")"], [":", ":"], ["[", "[]"], ["]", "]"], ["{", "{}"], ["}", "}"],
  ["=", "="], ["_", "_"], ["\"", "\"\""], ["'", "''"], [".", "."], [",", ","],
  ["+", "+"], ["-", "-"], ["*", "*"], ["/", "/"], ["<", "<"], [">", ">"], ["#", "# "],
  ["←", "left", "k-wide"], ["→", "right", "k-wide"], ["↶", "undo", "k-wide"],
];

export function keybar(root, editor) {
  root.classList.add("keybar");
  root.setAttribute("role", "toolbar");
  root.setAttribute("aria-label", "symbols");
  root.innerHTML = KEYS.map(([label, , cls], i) =>
    `<button type="button" class="${cls || ""}" data-k="${i}" aria-label="${label}">${label}</button>`).join("");
  root.addEventListener("pointerdown", (event) => {
    const button = event.target.closest("button[data-k]");
    if (!button) return;
    event.preventDefault();
    const [, action] = KEYS[Number(button.dataset.k)];
    const text = editor.text;
    if (action === "indent") editor.indent();
    else if (action === "dedent") editor.dedent();
    else if (action === "undo") { text.focus(); document.execCommand("undo"); }
    else if (action === "left" || action === "right") {
      text.focus({ preventScroll: true });
      const to = Math.max(0, text.selectionStart + (action === "left" ? -1 : 1));
      text.setSelectionRange(to, to);
    } else if (action.length === 2 && "()[]{}\"\"''".includes(action)) {
      // A pair: type both, leave the caret between them.
      editor.insert(action);
      const at = text.selectionStart - 1;
      text.setSelectionRange(at, at);
    } else editor.insert(action);
    if (navigator.vibrate && document.documentElement.dataset.haptics !== "off") navigator.vibrate(4);
  });
}
