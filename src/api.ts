// Firefox exposes the callback-style chrome.* namespace as an alias of
// browser.*, and Chrome has no browser.* at all. One global therefore serves
// both; the promise-returning forms of the MV3 APIs work on either side.
// Reach for webextension-polyfill only once an API turns out to differ.
declare const browser: typeof chrome | undefined;

export const api: typeof chrome =
  typeof browser !== 'undefined' ? browser : chrome;
