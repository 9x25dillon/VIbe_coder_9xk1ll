// A tagged template that escapes everything it is given unless told not to.
//
// Level briefs, test values, stdout and error messages all come from Python,
// and some of it from code the player wrote. None of it is ever markup, so
// every interpolation is escaped by default and only `raw()` opts out --
// which keeps the one unsafe path grep-able.

const RAW = Symbol("raw");

export function raw(text) {
  return { [RAW]: String(text) };
}

export function esc(text) {
  return String(text)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function render(value) {
  if (value === null || value === undefined || value === false) return "";
  if (Array.isArray(value)) return value.map(render).join("");
  if (typeof value === "object" && RAW in value) return value[RAW];
  return esc(value);
}

export function html(strings, ...values) {
  let out = strings[0];
  for (let i = 0; i < values.length; i += 1) out += render(values[i]) + strings[i + 1];
  return raw(out);
}

export function mount(element, template) {
  element.innerHTML = template[RAW];
  return element;
}

export const $ = (selector, root = document) => root.querySelector(selector);
export const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];

export const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

export function mmss(seconds) {
  const s = Math.max(0, Math.floor(seconds));
  return `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;
}
