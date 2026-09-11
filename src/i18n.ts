// The browser picks the language: `_locales/<lang>/messages.json`, with
// `default_locale` in the manifest as the fallback. This wraps the API
// so a page can translate itself from `data-i18n` attributes, and so a
// missing key shows up as the key instead of an empty string.
import { api } from './api.js';

export function t(key: string, ...args: string[]): string {
  const text = api.i18n?.getMessage(key, args);
  return text || key;
}

// A message may mark commands and addresses with backticks, the way
// Markdown does: `video-tldr serve`. Built through the DOM rather than
// innerHTML — a store reviewer sees UNSAFE_VAR_ASSIGNMENT for the latter,
// and every other part arrives as text that cannot turn into markup.
function setWithCode(node: HTMLElement, text: string): void {
  node.replaceChildren();
  text.split('`').forEach((part, index) => {
    if (!part) return;
    if (index % 2 === 0) {
      node.append(part);
      return;
    }
    const code = document.createElement('code');
    code.textContent = part;
    node.append(code);
  });
}

// Every element with data-i18n gets its text, data-i18n-placeholder its
// placeholder, data-i18n-title its tooltip. Called once per page load.
export function translate(root: ParentNode = document): void {
  root.querySelectorAll<HTMLElement>('[data-i18n]').forEach((node) => {
    const text = t(node.dataset.i18n!);
    // textContent unless there is something to mark up: it is the cheaper
    // path and the one that cannot be argued with.
    if (text.includes('`')) setWithCode(node, text);
    else node.textContent = text;
  });
  root
    .querySelectorAll<HTMLInputElement>('[data-i18n-placeholder]')
    .forEach((node) => {
      node.placeholder = t(node.dataset.i18nPlaceholder!);
    });
  root.querySelectorAll<HTMLElement>('[data-i18n-title]').forEach((node) => {
    node.title = t(node.dataset.i18nTitle!);
  });
}
