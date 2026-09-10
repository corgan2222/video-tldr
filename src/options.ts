import { api } from './api.js';
import { DEFAULT_BLOCKLIST } from './links.js';
import {
  BACKEND_FIELDS,
  BACKEND_INFO,
  DEFAULT_CHOICES,
  DEFAULT_CONNECTION,
  DEFAULT_SETTINGS,
  formatSeconds,
  request,
  STEP_LABEL,
  STEPS,
  type Config,
  type Connection,
  type Health,
  type Light,
  type Measure,
  type Stats,
} from './service.js';

function pick<T extends HTMLElement>(selector: string): T {
  return document.querySelector<T>(selector)!;
}

const blocklistBox = pick<HTMLTextAreaElement>('#blocklist');
const seenBox = pick<HTMLTextAreaElement>('#seen');
const seenCount = pick<HTMLElement>('#seen-count');
const status = pick<HTMLElement>('#status');

const serviceUrlBox = pick<HTMLInputElement>('#service-url');
const tokenBox = pick<HTMLInputElement>('#token');
const serviceStatus = pick<HTMLElement>('#service-status');
const formatsBox = pick<HTMLElement>('#formats');
const modelList = pick<HTMLDataListElement>('#models');
const modelHint = pick<HTMLElement>('#model-hint');
const backendInfo = pick<HTMLElement>('#backend-info');
const keyNote = pick<HTMLElement>('#key-note');
const statsBox = pick<HTMLElement>('#stats');
const statsNote = pick<HTMLElement>('#stats-note');

// Every key of config.json this page edits, by element. A select takes
// its choices from the service, so a backend added there shows up here
// without a release of the extension; a text field takes the value.
const FIELDS: Record<string, string> = {
  language: '#language',
  obsidian_vault: '#obsidian-vault',
  obsidian_folder: '#obsidian-folder',
  browser: '#browser',
  llm: '#llm',
  model: '#model',
  anthropic_api_key: '#anthropic-api-key',
  openai_api_key: '#openai-api-key',
  openai_base_url: '#openai-base-url',
  lmstudio_url: '#lmstudio-url',
  ollama_url: '#ollama-url',
  stt: '#stt',
};

// True once GET /config answered; only then does Save reach the service.
let connected = false;
let config: Config | undefined;

function field(key: string): HTMLInputElement | HTMLSelectElement {
  return pick<HTMLInputElement | HTMLSelectElement>(FIELDS[key]);
}

function message(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function connection(): Connection {
  return {
    serviceUrl: serviceUrlBox.value.trim() || DEFAULT_CONNECTION.serviceUrl,
    token: tokenBox.value.trim(),
  };
}

function fillSelect(
  select: HTMLSelectElement,
  choices: string[],
  value: string,
  describe: (choice: string) => string = (choice) => choice,
): void {
  select.replaceChildren(...choices.map((c) => new Option(describe(c), c)));
  select.value = value;
}

// The choice between fast and accurate, as `video-tldr models stt`
// prints it: speed class, leaderboard word error rate, languages.
function sttLabel(name: string): string {
  const spec = config?.stt_models[name];
  if (!spec) {
    if (name === 'auto') return 'auto (caption track when there is one)';
    if (name === 'subtitles') return 'subtitles (caption track only)';
    return name;
  }
  const rate = spec.wer ? `, WER ${spec.wer}` : '';
  return `${name} (${spec.speed}${rate}, ${spec.languages})`;
}

function checkbox(name: string, checked: boolean): HTMLLabelElement {
  const label = document.createElement('label');
  const box = document.createElement('input');
  box.type = 'checkbox';
  box.value = name;
  box.checked = checked;
  label.append(box, ` ${name}`);
  return label;
}

function light(id: string, name: string, state?: Light): void {
  const item = pick<HTMLElement>(`#light-${id}`);
  item.className = `light ${state ? (state.ok ? 'ok' : 'bad') : 'unknown'}`;
  item.textContent = `${name}: ${state?.detail ?? 'not checked yet'}`;
}

// The backend decides which extra fields make sense; the OpenAI key also
// serves the openai transcriber.
function showBackendFields(): void {
  const backend = field('llm').value;
  const needed = new Set(BACKEND_FIELDS[backend] ?? []);
  if (field('stt').value === 'openai') needed.add('openai_api_key');
  document.querySelectorAll<HTMLElement>('[data-field]').forEach((box) => {
    box.hidden = !needed.has(box.dataset.field ?? '');
  });
  keyNote.hidden =
    !needed.has('openai_api_key') && !needed.has('anthropic_api_key');
  const recommended = config?.default_models[backend] ?? '';
  backendInfo.textContent =
    (BACKEND_INFO[backend] ?? '') +
    (recommended ? ` Default model: ${recommended}.` : '');
  (field('model') as HTMLInputElement).placeholder = recommended
    ? `empty means ${recommended}`
    : 'pick one of the models the server has loaded';
}

// Fill the fields from the service's answer, or from the copy of its
// defaults when there is none yet.
function show(): void {
  const settings = config?.settings ?? DEFAULT_SETTINGS;
  const choices = config?.choices ?? DEFAULT_CHOICES;
  for (const key of Object.keys(FIELDS)) {
    const element = field(key);
    const value = settings[key] ?? '';
    if (element instanceof HTMLSelectElement) {
      fillSelect(
        element,
        choices[key] ?? [],
        value,
        key === 'stt' ? sttLabel : undefined,
      );
    } else {
      // Without a connection the placeholder shows the default; a value
      // typed here goes nowhere until Connect, and Save says so.
      element.value = config ? value : '';
    }
  }
  const browserBox = field('browser') as HTMLInputElement;
  browserBox.placeholder = config?.browser_found
    ? `found: ${config.browser_found}`
    : 'no Chrome or Edge found; choose one with Browse…';
  const chosen = new Set(
    (settings.formats ?? '').split(',').map((f) => f.trim()),
  );
  formatsBox.replaceChildren(
    ...(choices.formats ?? []).map((f) => checkbox(f, chosen.has(f))),
  );
  showBackendFields();
}

function table(head: string[], rows: string[][]): HTMLTableElement {
  const node = document.createElement('table');
  const header = node.insertRow();
  for (const text of head) {
    header.append(
      Object.assign(document.createElement('th'), { textContent: text }),
    );
  }
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

// Three small tables from GET /stats: the steps, the language models,
// the transcribers, each with what it took on this machine.
function showStats(stats: Stats): void {
  if (stats.runs === 0) {
    statsBox.replaceChildren();
    statsNote.textContent = 'No run yet; the first video fills this in.';
    return;
  }
  statsNote.textContent = `${stats.runs} runs on this machine; medians over the runs that did the step, cached steps left out.`;
  const measure = (name: string, m: Measure, seconds: string): string[] => [
    name,
    String(m.runs),
    seconds,
    `${m.input}+${m.output}`,
    m.usd ? m.usd.toFixed(3) : '0',
  ];
  statsBox.replaceChildren(
    table(
      ['Step', 'Median'],
      STEPS.filter((s) => s in stats.steps).map((s) => [
        STEP_LABEL[s] ?? s,
        formatSeconds(stats.steps[s]),
      ]),
    ),
    table(
      ['Language model', 'Runs', 'Summarise', 'Tokens per video', 'USD'],
      Object.entries(stats.models).map(([name, m]) =>
        measure(name, m, formatSeconds(m.seconds)),
      ),
    ),
    table(
      ['Transcriber', 'Runs', 'Transcribe'],
      Object.entries(stats.stt).map(([name, m]) => [
        name,
        String(m.runs),
        formatSeconds(m.seconds),
      ]),
    ),
  );
}

// What the chosen backend accepts as `model`, for the field's list; a
// backend that needs a key or a running server says so in the hint.
async function loadModels(): Promise<void> {
  const backend = field('llm').value;
  if (!connected) {
    modelHint.textContent = 'Connect to list the models of this backend.';
    return;
  }
  try {
    const { models } = await request<{ models: string[] }>(
      connection(),
      'GET',
      `/models?llm=${encodeURIComponent(backend)}`,
    );
    modelList.replaceChildren(...models.map((m) => new Option(m)));
    modelHint.textContent = `${models.length} models at ${backend}.`;
  } catch (error) {
    modelList.replaceChildren();
    modelHint.textContent = message(error);
  }
}

// The three lights: asked once per connect, the service asks its
// backend and looks for the transcriber's model.
async function loadHealth(): Promise<void> {
  try {
    const health = await request<Health>(connection(), 'GET', '/health');
    light('service', 'Service', health.service);
    light('llm', 'Language model', health.llm);
    light('stt', 'Transcriber', health.stt);
  } catch (error) {
    light('service', 'Service', { ok: false, detail: message(error) });
    light('llm', 'Language model');
    light('stt', 'Transcriber');
  }
}

async function loadService(): Promise<void> {
  try {
    config = await request<Config>(connection(), 'GET', '/config');
    connected = true;
    show();
    serviceStatus.textContent = `Connected to the video-tldr service ${config.version}, data under ${config.home}, log in ${config.log}.`;
    showStats(await request<Stats>(connection(), 'GET', '/stats'));
  } catch (error) {
    connected = false;
    config = undefined;
    show();
    serviceStatus.textContent = `Not connected: ${message(error)}`;
    statsNote.textContent = 'Connect to see what your runs took.';
  }
  await Promise.all([loadModels(), loadHealth()]);
}

// Every field goes back as it stands. A key the service showed as stars
// goes back as stars, which the service takes as "keep it"; an emptied
// field removes the key.
async function saveService(): Promise<void> {
  const values: Record<string, string> = {};
  for (const key of Object.keys(FIELDS)) values[key] = field(key).value.trim();
  values.formats = Array.from(
    formatsBox.querySelectorAll<HTMLInputElement>('input:checked'),
    (box) => box.value,
  ).join(',');
  await request(connection(), 'PUT', '/config', values);
}

// A file or folder dialog on the desktop, opened by the service: the
// browser's own dialog never tells an extension the full path.
async function browse(key: string, kind: 'file' | 'folder'): Promise<void> {
  const box = field(key) as HTMLInputElement;
  try {
    const { path } = await request<{ path: string }>(
      connection(),
      'POST',
      '/pick',
      {
        kind,
        start: box.value.trim(),
      },
    );
    if (path) box.value = path;
  } catch (error) {
    say(message(error));
  }
}

function say(text: string): void {
  status.textContent = text;
  setTimeout(() => {
    status.textContent = '';
  }, 6000);
}

async function load(): Promise<void> {
  const stored = await api.storage.local.get({
    blocklist: DEFAULT_BLOCKLIST,
    seen: [] as string[],
    ...DEFAULT_CONNECTION,
  });
  blocklistBox.value = (stored.blocklist as string[]).join('\n');
  const seen = stored.seen as string[];
  seenBox.value = seen.join('\n');
  seenCount.textContent = `${seen.length} links`;
  serviceUrlBox.value = stored.serviceUrl as string;
  tokenBox.value = stored.token as string;
  await loadService();
}

pick('#connect').addEventListener('click', async () => {
  await api.storage.local.set(connection());
  await loadService();
});

field('llm').addEventListener('change', () => {
  showBackendFields();
  void loadModels();
});
field('stt').addEventListener('change', showBackendFields);
pick('#pick-vault').addEventListener('click', () => {
  void browse('obsidian_vault', 'folder');
});
pick('#pick-browser').addEventListener('click', () => {
  void browse('browser', 'file');
});

pick('#save').addEventListener('click', async () => {
  const blocklist = blocklistBox.value
    .split('\n')
    .map((line) => line.trim().toLowerCase())
    .filter((line) => line.length > 0);
  await api.storage.local.set({ blocklist, ...connection() });
  if (!connected) {
    say(
      'Saved the blocklist and the connection; press Connect to save the rest.',
    );
    return;
  }
  try {
    await saveService();
    await loadHealth();
  } catch (error) {
    say(message(error));
    return;
  }
  say('Saved.');
});

pick('#clear').addEventListener('click', async () => {
  await api.storage.local.set({ seen: [] });
  await load();
  say('Forgotten.');
});

void load();
