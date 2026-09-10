// A Manifest V3 service worker restarts between events, so nothing here
// relies on module-level state surviving from one event to the next: the
// running job lives in storage.local, and an alarm wakes the worker to
// poll it.
//
// The manifest lists this file under both `service_worker` and `scripts`:
// Chrome reads the former, Firefox the latter, and each ignores the key it
// does not understand. Both load it as an ES module (`"type": "module"` in
// the manifest), because tsc emits modules. Firefox does that since 112 and
// reads `data_collection_permissions` since 140 (Android: 142), which is
// where the manifest pins `strict_min_version`.
import { api } from './api.js';
import { DEFAULT_BLOCKLIST, planOpen, type Selection } from './links.js';
import {
  badgeFor,
  DEFAULT_CONNECTION,
  failureBadge,
  HOST_PATTERN,
  request,
  type Badge,
  type Connection,
  type Job,
} from './service.js';

const MENU_ID = 'open-all-links';
const POLL_ALARM = 'poll-job';
// Chrome's floor for a repeating alarm; a job takes minutes anyway.
const POLL_MINUTES = 0.5;

api.runtime.onInstalled.addListener(() => {
  api.contextMenus.create({
    id: MENU_ID,
    title: 'Open all links',
    contexts: ['selection'],
  });
});

// ---------------------------------------------------------------- video job

async function connection(): Promise<Connection> {
  return (await api.storage.local.get(DEFAULT_CONNECTION)) as Connection;
}

async function showBadge(badge: Badge): Promise<void> {
  await api.action.setBadgeBackgroundColor({ color: badge.color });
  await api.action.setBadgeText({ text: badge.text });
  await api.action.setTitle({ title: badge.title });
}

function message(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

// The toolbar icon hands the active tab's URL to the service. Firefox
// grants a host permission only when asked, Chrome at install time; asked
// first thing in the click handler, both answer at once when it is granted.
// First thing on purpose: Firefox counts the request as user input only
// until the first await, so nothing may run before it.
api.action.onClicked.addListener(async (tab) => {
  const granted = await api.permissions.request({ origins: [HOST_PATTERN] });
  if (!granted) {
    await showBadge(failureBadge('no permission to reach 127.0.0.1'));
    return;
  }
  try {
    const job = await request<Job>(await connection(), 'POST', '/jobs', {
      url: tab.url,
    });
    await api.storage.local.set({ job: job.id });
    await showBadge(badgeFor(job));
    await api.alarms.create(POLL_ALARM, { periodInMinutes: POLL_MINUTES });
  } catch (error) {
    await showBadge(failureBadge(message(error)));
  }
});

async function finish(job: Job): Promise<void> {
  await api.alarms.clear(POLL_ALARM);
  await api.storage.local.set({ job: '' });
  const what = job.title ?? job.id;
  await api.notifications.create(`${job.status}:${job.id}`, {
    type: 'basic',
    iconUrl: api.runtime.getURL('icons/128.png'),
    title:
      job.status === 'done'
        ? 'corganshelper: summary ready'
        : `corganshelper: ${job.error?.step ?? 'job'} failed`,
    message:
      job.status === 'done'
        ? `${what}. Click to open it.`
        : `${what}: ${job.error?.message ?? 'unknown error'}`,
  });
}

async function poll(): Promise<void> {
  const { job: id } = (await api.storage.local.get({ job: '' })) as {
    job: string;
  };
  if (!id) {
    await api.alarms.clear(POLL_ALARM);
    return;
  }
  let job: Job;
  try {
    job = await request<Job>(await connection(), 'GET', `/jobs/${id}`);
  } catch (error) {
    await showBadge(failureBadge(message(error)));
    await api.alarms.clear(POLL_ALARM);
    return;
  }
  await showBadge(badgeFor(job));
  if (job.status === 'done' || job.status === 'error') await finish(job);
}

api.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === POLL_ALARM) void poll();
});

// The notification's id carries the outcome: only a finished summary has
// something to open, and the service opens it (the note in Obsidian, else
// the first document it wrote).
api.notifications.onClicked.addListener(async (id) => {
  const [status, jobId] = id.split(':', 2);
  await api.notifications.clear(id);
  if (status !== 'done' || !jobId) return;
  try {
    await request(await connection(), 'POST', `/jobs/${jobId}/open`);
  } catch (error) {
    await showBadge(failureBadge(message(error)));
  }
});

// ----------------------------------------------------------- open all links

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
