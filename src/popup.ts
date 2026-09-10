// The window behind the toolbar icon: what the service is doing with the
// video in this tab, how long it will take, where the result went, and
// the buttons that start, cancel and open a run. Starting, cancelling
// and opening go through the background worker, because this page dies
// when it closes; reading is done here, every two seconds while it is
// open.
import { api } from './api.js';
import { t, translate } from './i18n.js';
import {
  DEFAULT_CHOICES,
  DEFAULT_CONNECTION,
  formatSeconds,
  HOST_PATTERN,
  NoServiceError,
  progress,
  remainingSeconds,
  request,
  STEP_KEY,
  STEPS,
  stepViews,
  videoId,
  type Config,
  type Connection,
  type Health,
  type Job,
  type Light,
  type Profile,
  type RunOptions,
  type Stats,
} from './service.js';

function pick<T extends HTMLElement>(selector: string): T {
  return document.querySelector<T>(selector)!;
}

const videoBox = pick<HTMLElement>('#video');
const jobsBox = pick<HTMLElement>('#jobs');
const logBox = pick<HTMLPreElement>('#log');
const logDetails = pick<HTMLDetailsElement>('#log-box');
const statsDetails = pick<HTMLDetailsElement>('#stats-box');
const statsBox = pick<HTMLElement>('#stats');
const noService = pick<HTMLElement>('#no-service');
const status = pick<HTMLElement>('#status');
const buttons = {
  fast: pick<HTMLButtonElement>('#fast'),
  thorough: pick<HTMLButtonElement>('#thorough'),
};
const switches = {
  timestamps: pick<HTMLInputElement>('#timestamps'),
  condensed: pick<HTMLInputElement>('#condensed'),
  cleanup: pick<HTMLInputElement>('#cleanup'),
};
const languageBox = pick<HTMLSelectElement>('#language');
const styleBox = pick<HTMLSelectElement>('#style');

const REFRESH_MS = 2000;
const LOG_LINES = 40;
const EMPTY_STATS: Stats = { runs: 0, steps: {}, models: {}, stt: {} };

let connection: Connection = DEFAULT_CONNECTION;
let tabUrl = '';
let currentId: string | null = null;
let stats: Stats = EMPTY_STATS;
let config: Config | undefined;

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
// background still tracks, so a queue is visible while it works off.
async function jobIds(): Promise<string[]> {
  const { jobs } = (await api.storage.local.get({ jobs: [] as string[] })) as {
    jobs: string[];
  };
  return [...new Set(currentId ? [currentId, ...jobs] : jobs)];
}

function options(): RunOptions {
  return {
    timestamps: switches.timestamps.checked ? 'on' : 'off',
    condensed: switches.condensed.checked ? 'on' : 'off',
    cleanup: switches.cleanup.checked ? 'on' : 'off',
    style: styleBox.value,
  };
}

function bar(fraction: number): HTMLElement {
  const outer = element('div', undefined, 'bar');
  const inner = element('div');
  inner.style.width = `${Math.round(fraction * 100)}%`;
  outer.append(inner);
  return outer;
}

function iconButton(
  label: string,
  symbol: string,
  onClick: () => void,
): HTMLButtonElement {
  const button = element('button', `${symbol} ${label}`, 'icon');
  button.title = label;
  button.addEventListener('click', onClick);
  return button;
}

function renderJob(job: Job, now: Date): HTMLElement {
  const box = element('div', undefined, 'job');
  const title = element('h3', job.title ?? job.id);
  title.title = job.title ?? job.id;
  box.append(title);
  const facts = [
    t(job.status),
    job.status === 'queued' && job.position
      ? t('waitingPosition', String(job.position))
      : null,
    job.profile ? t(job.profile) : null,
    job.model,
    job.stt ? `${t('transcriber')} ${job.stt}` : null,
  ].filter(Boolean) as string[];
  box.append(element('div', facts.join(' · '), 'facts'));

  const list = element('ul', undefined, 'steps');
  for (const view of stepViews(job, stats, now)) {
    const item = element('li', undefined, view.state);
    const mark = { done: '✓', running: '▶', pending: '·', failed: '✗' }[
      view.state
    ];
    const left = element('span');
    left.append(element('span', mark, 'mark'), t(view.labelKey));
    item.append(left);
    const seconds =
      view.seconds === null
        ? ''
        : view.state === 'pending'
          ? `~${formatSeconds(view.seconds)}`
          : formatSeconds(view.seconds);
    item.append(element('span', seconds, 'secs'));
    list.append(item);
  }
  box.append(list);

  if (job.status === 'queued' || job.status === 'running') {
    box.append(bar(progress(job, stats, now)));
    const left = remainingSeconds(job, stats, now);
    box.append(
      element(
        'div',
        left === null ? t('noEstimate') : t('aboutLeft', formatSeconds(left)),
        'facts',
      ),
    );
    const row = element('div', undefined, 'row');
    row.append(
      iconButton(t('cancel'), '✕', () => {
        void ask({ type: 'cancel', id: job.id });
      }),
    );
    box.append(row);
  }
  if (job.error) {
    box.append(
      element(
        'div',
        `${t(STEP_KEY[job.error.step] ?? job.error.step)}: ${job.error.message}`,
        'error',
      ),
    );
  }
  if (job.status === 'done') {
    const cost = [
      job.seconds !== undefined ? t('took', formatSeconds(job.seconds)) : null,
      job.images !== undefined ? t('pictures', String(job.images)) : null,
      job.input !== undefined
        ? t('tokens', `${job.input}+${job.output}`)
        : null,
      job.tokens_per_second
        ? t('tokensPerSecond', job.tokens_per_second.toFixed(1))
        : null,
      job.usd ? `${job.usd.toFixed(3)} USD` : null,
    ].filter(Boolean) as string[];
    box.append(element('div', cost.join(' · '), 'facts'));
    const row = element('div', undefined, 'row');
    if (job.written?.obsidian) {
      row.append(
        iconButton(t('openNote'), '🟣', () => {
          void ask({ type: 'open', id: job.id, what: 'obsidian' });
        }),
      );
    }
    row.append(
      iconButton(t('openFolder'), '📁', () => {
        void ask({ type: 'open', id: job.id, what: 'folder' });
      }),
    );
    box.append(row);
    const files = element('div', undefined, 'files');
    for (const [kind, path] of Object.entries(job.written ?? {})) {
      files.append(element('div', `${kind}: ${path}`));
    }
    box.append(files);
  }
  return box;
}

async function ask(what: object): Promise<unknown> {
  const reply = (await api.runtime.sendMessage(what)) as
    { error?: string } | undefined;
  if (reply?.error) {
    say(reply.error, true);
    throw new Error(reply.error);
  }
  say('');
  await refresh();
  return reply;
}

function table(head: string[], rows: string[][]): HTMLTableElement {
  const node = document.createElement('table');
  const header = node.insertRow();
  head.forEach((text, index) => {
    const cell = document.createElement('th');
    cell.textContent = text;
    if (index > 0) cell.className = 'n';
    header.append(cell);
  });
  for (const cells of rows) {
    const row = node.insertRow();
    cells.forEach((text, index) => {
      const cell = row.insertCell();
      cell.textContent = text;
      if (index > 0) cell.className = 'n';
    });
  }
  return node;
}

function showStats(): void {
  if (stats.runs === 0) {
    statsBox.replaceChildren(element('p', t('statsEmpty'), 'help'));
    return;
  }
  statsBox.replaceChildren(
    table(
      [t('colStep'), t('colMedian')],
      STEPS.filter((s) => s in stats.steps).map((s) => [
        t(STEP_KEY[s] ?? s),
        formatSeconds(stats.steps[s]),
      ]),
    ),
    table(
      [t('colModel'), t('colRuns'), t('colSummarise'), t('colTokensPerSecond')],
      Object.entries(stats.models).map(([name, m]) => [
        name,
        String(m.runs),
        formatSeconds(m.seconds),
        m.tokens_per_second ? m.tokens_per_second.toFixed(1) : '',
      ]),
    ),
    table(
      [t('colTranscribe'), t('colRuns'), t('colMedian')],
      Object.entries(stats.stt).map(([name, m]) => [
        name,
        String(m.runs),
        formatSeconds(m.seconds),
      ]),
    ),
  );
}

async function refresh(): Promise<void> {
  const now = new Date();
  const jobs: Job[] = [];
  for (const id of await jobIds()) {
    try {
      jobs.push(await request<Job>(connection, 'GET', `/jobs/${id}`));
    } catch (error) {
      // The job for this tab may not exist yet; a dead service is shown
      // by the box above, not once per job.
      if (error instanceof NoServiceError) {
        offline(true);
        return;
      }
      if (id !== currentId) say(message(error), true);
    }
  }
  offline(false);
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

// No service: the buttons make no sense, and the command to start it
// does. Shown once, not per failed request.
function offline(yes: boolean): void {
  noService.hidden = !yes;
  if (yes) {
    buttons.fast.disabled = true;
    buttons.thorough.disabled = true;
    jobsBox.replaceChildren();
  } else if (currentId) {
    buttons.fast.disabled = false;
    buttons.thorough.disabled = false;
  }
}

async function start(profile: Profile): Promise<void> {
  // First thing on purpose: Firefox counts the request as user input only
  // until the first await, so nothing may run before it.
  const granted = await api.permissions.request({ origins: [HOST_PATTERN] });
  if (!granted) {
    say('No permission to reach 127.0.0.1.', true);
    return;
  }
  try {
    await ask({
      type: 'start',
      url: tabUrl,
      profile,
      options: options(),
      language: languageBox.value,
    });
    logDetails.open = true;
  } catch {
    // ask() already showed the reason.
  }
}

// A dot with the name beside it; the detail is the tooltip, and a red
// one puts its reason in the status line, where it can be read.
function light(id: string, name: string, state?: Light): void {
  const dot = pick<HTMLElement>(`#light-${id}`);
  dot.className = `light ${state ? (state.ok ? 'ok' : 'bad') : 'unknown'}`;
  dot.title = state?.detail ?? t('notChecked');
  const what = element('span', name, 'what');
  dot.replaceChildren(what);
  if (state && !state.ok) say(state.detail, true);
}

function say(text: string, bad = false): void {
  status.textContent = text;
  status.className = bad ? 'status bad' : 'status';
}

async function showLights(): Promise<void> {
  try {
    const health = await request<Health>(connection, 'GET', '/health');
    light('service', t('lightService'), health.service);
    light('llm', t('lightLlm'), health.llm);
    light('stt', t('lightStt'), health.stt);
    // A model that takes no images or has too small a context: the run
    // would fail late, so the reason belongs here, before the click.
    if (health.capabilities && !health.capabilities.ok) {
      say(health.capabilities.detail, true);
    }
  } catch (error) {
    offline(error instanceof NoServiceError);
    light('service', t('lightService'), { ok: false, detail: message(error) });
    light('llm', t('lightLlm'));
    light('stt', t('lightStt'));
  }
}

async function load(): Promise<void> {
  translate();
  pick<HTMLElement>('#start-command').textContent = t('noServiceCommand');
  connection = (await api.storage.local.get(DEFAULT_CONNECTION)) as Connection;
  const [tab] = await api.tabs.query({ active: true, currentWindow: true });
  tabUrl = tab?.url ?? '';
  currentId = videoId(tabUrl);
  videoBox.textContent = currentId
    ? (tab?.title ?? '').replace(/ - YouTube$/, '')
    : t('popupNoVideo');
  videoBox.title = tabUrl;
  if (currentId) {
    buttons.fast.disabled = false;
    buttons.thorough.disabled = false;
  } else {
    say(t('popupOpenVideo'));
  }

  try {
    config = await request<Config>(connection, 'GET', '/config');
    stats = await request<Stats>(connection, 'GET', '/stats');
  } catch (error) {
    if (error instanceof NoServiceError) offline(true);
  }
  const settings = config?.settings ?? {};
  const choices = config?.choices ?? DEFAULT_CHOICES;
  switches.timestamps.checked = (settings.timestamps ?? 'on') === 'on';
  switches.condensed.checked = settings.condensed === 'on';
  switches.cleanup.checked = settings.cleanup === 'on';
  for (const [box, key] of [
    [languageBox, 'language'],
    [styleBox, 'style'],
  ] as const) {
    box.replaceChildren(...(choices[key] ?? []).map((c) => new Option(c, c)));
    box.value = settings[key] ?? (key === 'language' ? 'de' : 'normal');
  }
  showStats();
  void showLights();
  await refresh();
  setInterval(() => void refresh(), REFRESH_MS);
}

pick('#settings').addEventListener('click', () => {
  void api.runtime.openOptionsPage();
});
buttons.fast.addEventListener('click', () => void start('fast'));
buttons.thorough.addEventListener('click', () => void start('thorough'));
logDetails.addEventListener('toggle', () => void refresh());
statsDetails.addEventListener('toggle', showStats);
pick('#copy-command').addEventListener('click', async () => {
  await navigator.clipboard.writeText(t('noServiceCommand'));
  say(t('copied'));
});
// The language of the note is changed often, so it is saved right here.
languageBox.addEventListener('change', () => {
  void request(connection, 'PUT', '/config', {
    language: languageBox.value,
  }).catch((error: unknown) => {
    say(message(error), true);
  });
});

void load();
