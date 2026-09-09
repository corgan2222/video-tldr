// A Manifest V3 service worker restarts between events, so nothing here
// relies on module-level state surviving from one event to the next.
//
// The manifest lists this file under both `service_worker` and `scripts`:
// Chrome reads the former, Firefox the latter, and each ignores the key it
// does not understand. Both load it as an ES module (`"type": "module"` in
// the manifest), because tsc emits modules. Firefox does that since 112 and
// reads `data_collection_permissions` since 140 (Android: 142), which is
// where the manifest pins `strict_min_version`.
import { api } from './api.js';
import { DEFAULT_BLOCKLIST, planOpen, type Selection } from './links.js';

const MENU_ID = 'open-all-links';

api.runtime.onInstalled.addListener(() => {
  api.contextMenus.create({
    id: MENU_ID,
    title: 'Open all links',
    contexts: ['selection'],
  });
});

// Until the video pipeline lands, the toolbar icon opens the options.
api.action.onClicked.addListener(() => {
  void api.runtime.openOptionsPage();
});

// Runs inside the page, serialised by executeScript: it must not close over
// anything from this module. `selectionText` from the menu event carries
// only visible characters, which YouTube shortens with an ellipsis, so the
// anchors inside the selection are read here with their full href.
function readSelection(): Selection {
  const selection = window.getSelection();
  const hrefs: string[] = [];
  if (!selection) return { hrefs, text: '' };
  for (let i = 0; i < selection.rangeCount; i += 1) {
    const fragment = selection.getRangeAt(i).cloneContents();
    fragment.querySelectorAll('a[href]').forEach((a) => {
      hrefs.push((a as HTMLAnchorElement).href);
    });
  }
  return { hrefs, text: selection.toString() };
}

api.contextMenus.onClicked.addListener(async (info, tab) => {
  if (info.menuItemId !== MENU_ID || tab?.id === undefined) return;
  const [injected] = await api.scripting.executeScript({
    target: { tabId: tab.id },
    func: readSelection,
  });
  const selection = (injected?.result as Selection | undefined) ?? {
    hrefs: [],
    text: info.selectionText ?? '',
  };
  const stored = await api.storage.local.get({
    blocklist: DEFAULT_BLOCKLIST,
    seen: [] as string[],
  });
  const seen = new Set<string>(stored.seen as string[]);
  const plan = planOpen(selection, stored.blocklist as string[], seen);
  if (plan.open.length > 0) {
    await api.windows.create({ url: plan.open });
    await api.storage.local.set({ seen: [...seen, ...plan.open] });
  }
  await api.action.setBadgeText({ text: String(plan.open.length) });
  await api.action.setTitle({
    title: `corganshelper: ${plan.open.length} opened, ${plan.known} known, ${plan.blocked} blocked`,
  });
  // The worker may be gone before this fires; then the badge stays until
  // the next click, which is fine.
  setTimeout(() => {
    void api.action.setBadgeText({ text: '' });
  }, 5000);
});
