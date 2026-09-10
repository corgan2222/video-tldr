// The browser picks the language: `_locales/<lang>/messages.json`, with
// `default_locale` in the manifest as the fallback. This wraps the API
// so a page can translate itself from `data-i18n` attributes, and so a
// missing key shows up as the key instead of an empty string.
import { api } from './api.js';

export function t(key: string, ...args: string[]): string {
  const text = api.i18n?.getMessage(key, args);
  return text || key;
}

// Every element with data-i18n gets its text, data-i18n-placeholder its
// placeholder, data-i18n-title its tooltip. Called once per page load.
export function translate(root: ParentNode = document): void {
  root.querySelectorAll<HTMLElement>('[data-i18n]').forEach((node) => {
    node.textContent = t(node.dataset.i18n!);
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
