// Firefox exposes the callback-style chrome.* namespace as an alias of
// browser.*, and Chrome has no browser.* at all. One global therefore serves
// both; the promise-returning forms of the MV3 APIs work on either side.
// Reach for webextension-polyfill only once an API turns out to differ.
import { HOST_PATTERN } from './service.js';

declare const browser: typeof chrome | undefined;

export const api: typeof chrome =
  typeof browser !== 'undefined' ? browser : chrome;

// The host permission is optional, so installing the extension raises no
// warning about 127.0.0.1 and both stores have less to ask about. The
// price is that every page must check before it talks to the service.
export function hasAccess(): Promise<boolean> {
  return api.permissions.contains({ origins: [HOST_PATTERN] });
}

// Firefox counts a click as user input only until the first await, so
// this belongs first in a click handler, before anything else runs.
export function askAccess(): Promise<boolean> {
  return api.permissions.request({ origins: [HOST_PATTERN] });
}
