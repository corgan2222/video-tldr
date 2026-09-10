// The window behind the toolbar icon: what the service is doing with the
// video in this tab, how long it will take, where the result went, and
// the two buttons that start a run. Starting and opening go through the
// background worker, because this page dies when it closes; reading is
// done here, every two seconds while it is open.
import { api } from './api.js';
import {
  DEFAULT_CONNECTION,
  formatSeconds,
  HOST_PATTERN,
  remainingSeconds,
  request,
  stepViews,
  videoId,
  type Connection,
  type Job,
  type Profile,
  type Stats,
} from './service.js';

function pick<T extends HTMLElement>(selector: string): T {
  return document.querySelector<T>(selector)!;
}

const videoBox = pick<HTMLElement>('#video');
const hint = pick<HTMLElement>('#hint');
const jobsBox = pick<HTMLElement>('#jobs');
const logBox = pick<HTMLPreElement>('#log');
const logDetails = pick<HTMLDetailsElement>('#log-box');
const status = pick<HTMLElement>('#status');
const buttons = {
  fast: pick<HTMLButtonElement>('#fast'),
  thorough: pick<HTMLButtonElement>('#thorough'),
};

const REFRESH_MS = 2000;
const LOG_LINES = 40;
const EMPTY_STATS: Stats = { runs: 0, steps: {}, models: {}, stt: {} };

let connection: Connection = DEFAULT_CONNECTION;
let tabUrl = '';
let tabTitle = '';
let currentId: string | null = null;
let stats: Stats = EMPTY_STATS;

function message(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function element<K extends keyof HTMLElementTagNameMap>(
  tag: K,
  text?: string,
  className?: string,
): HTMLElementTagNameMap[K] {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (className) node.className = className;
  return node;
}

// The jobs worth showing: the one for this tab first, then every job the
// background still tracks.
async function jobIds(): Promise<string[]> {
  const { jobs } = (await api.storage.local.get({ jobs: [] as string[] })) as {
    jobs: string[];
  };
  const ids = currentId ? [currentId, ...jobs] : jobs;
  return [...new Set(ids)];
}

function renderJob(job: Job, now: Date): HTMLElement {
  const box = element('div', undefined, 'job');
  box.append(element('h2', job.title ?? job.id));
  const facts = [
    job.status,
    job.profile ? `${job.profile} profile` : null,
    job.model ? `model ${job.model}` : null,
    job.stt ? `transcriber ${job.stt}` : null,
  ].filter(Boolean);
  box.append(element('div', facts.join(' · '), 'note'));

  const list = element('ul', undefined, 'steps');
  for (const view of stepViews(job, stats, now)) {
    const item = element('li', undefined, view.state);
    const mark = { done: '✓', running: '▶', pending: '·', failed: '✗' }[
      view.state
    ];
    item.append(element('span', `${mark} ${view.label}`));
    const seconds =
      view.seconds === null
        ? ''
        : view.state === 'pending'
          ? `~${formatSeconds(view.seconds)}`
          : formatSeconds(view.seconds);
    item.append(element('span', seconds));
    list.append(item);
  }
  box.append(list);

  if (job.status === 'queued' || job.status === 'running') {
    const left = remainingSeconds(job, stats, now);
    box.append(
      element(
        'div',
        left === null
          ? 'No earlier run to estimate from.'
          : `About ${formatSeconds(left)} left.`,
        'note',
      ),
    );
  }
  if (job.status === 'error' && job.error) {
    box.append(
      element('div', `${job.error.step} failed: ${job.error.message}`, 'error'),
    );
  }
  if (job.status === 'done') {
    const cost = [
      job.seconds !== undefined ? `took ${formatSeconds(job.seconds)}` : null,
      job.images !== undefined ? `${job.images} pictures` : null,
      job.input !== undefined ? `${job.input}+${job.output} tokens` : null,
      job.usd ? `${job.usd.toFixed(3)} USD` : null,
    ].filter(Boolean);
    box.append(element('div', cost.join(' · '), 'note'));
    const outputs = element('div', undefined, 'outputs');
    const open = element('button', 'Open result');
    open.addEventListener('click', () => {
      void ask({ type: 'open', id: job.id });
    });
    outputs.append(open);
    box.append(outputs);
    for (const [kind, path] of Object.entries(job.written ?? {})) {
      box.append(element('div', `${kind}: ${path}`, 'note'));
    }
  }
  return box;
}

async function ask(what: object): Promise<unknown> {
  const reply = (await api.runtime.sendMessage(what)) as
    { error?: string } | undefined;
  if (reply?.error) {
    status.textContent = reply.error;
    throw new Error(reply.error);
  }
  return reply;
}

async function refresh(): Promise<void> {
  const now = new Date();
  const ids = await jobIds();
  const jobs: Job[] = [];
  for (const id of ids) {
    try {
      jobs.push(await request<Job>(connection, 'GET', `/jobs/${id}`));
    } catch (error) {
      // The job for this tab may not exist yet; anything else is worth a line.
      if (id !== currentId) status.textContent = message(error);
    }
  }
  jobsBox.replaceChildren(...jobs.map((job) => renderJob(job, now)));
  if (logDetails.open) {
    try {
      const { lines } = await request<{ lines: string[] }>(
        connection,
        'GET',
        `/log?lines=${LOG_LINES}`,
      );
      logBox.textContent = lines.join('\n');
      logBox.scrollTop = logBox.scrollHeight;
    } catch (error) {
      logBox.textContent = message(error);
    }
  }
}

async function start(profile: Profile): Promise<void> {
  // First thing on purpose: Firefox counts the request as user input only
  // until the first await, so nothing may run before it.
  const granted = await api.permissions.request({ origins: [HOST_PATTERN] });
  if (!granted) {
    status.textContent = 'No permission to reach 127.0.0.1.';
    return;
  }
  status.textContent = `Starting the ${profile} run…`;
  try {
    await ask({ type: 'start', url: tabUrl, profile });
    status.textContent = '';
    logDetails.open = true;
    await refresh();
  } catch {
    // ask() already showed the reason.
  }
}

async function load(): Promise<void> {
  connection = (await api.storage.local.get(DEFAULT_CONNECTION)) as Connection;
  const [tab] = await api.tabs.query({ active: true, currentWindow: true });
  tabUrl = tab?.url ?? '';
  tabTitle = tab?.title ?? '';
  currentId = videoId(tabUrl);
  videoBox.textContent = currentId
    ? tabTitle.replace(/ - YouTube$/, '')
    : 'No YouTube video in this tab.';
  videoBox.title = tabUrl;

  if (!connection.token) {
    hint.textContent = 'Not set up yet: open Settings, paste the token.';
  } else if (!currentId) {
    hint.textContent = 'Open a YouTube video first.';
  } else {
    buttons.fast.disabled = false;
    buttons.thorough.disabled = false;
  }
  try {
    stats = await request<Stats>(connection, 'GET', '/stats');
  } catch (error) {
    if (connection.token) status.textContent = message(error);
  }
  await refresh();
  setInterval(() => void refresh(), REFRESH_MS);
}

pick('#settings').addEventListener('click', () => {
  void api.runtime.openOptionsPage();
});
buttons.fast.addEventListener('click', () => void start('fast'));
buttons.thorough.addEventListener('click', () => void start('thorough'));
logDetails.addEventListener('toggle', () => void refresh());

void load();
