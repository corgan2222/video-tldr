// A Manifest V3 service worker restarts between events, so nothing here
// should rely on module-level state surviving from one message to the next.
//
// The manifest lists this file under both `service_worker` and `scripts`:
// Chrome reads the former, Firefox the latter, and each ignores the key it
// does not understand. Both load it as an ES module (`"type": "module"` in
// the manifest), because tsc emits modules. Firefox does that since 112 and
// reads `data_collection_permissions` since 140 (Android: 142), which is
// where the manifest pins `strict_min_version`.
//
// Firefox exposes the callback-style chrome.* namespace as an alias of
// browser.*, and Chrome has no browser.* at all. One global therefore serves
// both for callback APIs; reach for webextension-polyfill only once a
// promise-based API is needed.
declare const browser: typeof chrome | undefined;
const api = typeof browser !== 'undefined' ? browser : chrome;

api.runtime.onInstalled.addListener(() => {
  console.log('corganshelper installed');
});
