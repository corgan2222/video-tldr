import { api } from './api.js';
import { t, translate } from './i18n.js';
import { DEFAULT_BLOCKLIST } from './links.js';
import {
  BACKEND_FIELDS,
  BACKEND_INFO,
  DEFAULT_CHOICES,
  DEFAULT_CONNECTION,
  DEFAULT_SETTINGS,
  formatSeconds,
  NoServiceError,
  request,
  STEP_KEY,
  STEPS,
  type BenchRow,
  type Config,
  type Connection,
  type Health,
  type Job,
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
const noService = pick<HTMLElement>('#no-service');
const formatsBox = pick<HTMLElement>('#formats');
const modelList = pick<HTMLDataListElement>('#models');
const modelHint = pick<HTMLElement>('#model-hint');
const backendInfo = pick<HTMLElement>('#backend-info');
const keyNote = pick<HTMLElement>('#key-note');
const statsBox = pick<HTMLElement>('#stats');
const statsNote = pick<HTMLElement>('#stats-note');
const benchModels = pick<HTMLElement>('#bench-models');
const benchStatus = pick<HTMLElement>('#bench-status');
const benchResult = pick<HTMLElement>('#bench-result');

// Every key of config.json this page edits, by element. A select takes
// its choices from the service, so a backend added there shows up here
// without a release of the extension; a text field takes the value.
const FIELDS: Record<string, string> = {
  language: '#language',
  style: '#style',
  download_dir: '#download-dir',
  obsidian_vault: '#obsidian-vault',
  obsidian_folder: '#obsidian-folder',
  browser: '#browser',
  pdf_template: '#pdf-template',
  llm: '#llm',
  model: '#model',
  anthropic_api_key: '#anthropic-api-key',
  openai_api_key: '#openai-api-key',
  openai_base_url: '#openai-base-url',
  lmstudio_url: '#lmstudio-url',
  ollama_url: '#ollama-url',
  stt: '#stt',
};

// True once GET /config answered; only then does a change reach the
// service.
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
    if (name === 'auto') return 'auto';
    return name;
  }
  const rate = spec.wer ? `, WER ${spec.wer}` : '';
  return `${name} (${spec.speed}${rate}, ${spec.languages})`;
}

function checkbox(
  name: string,
  checked: boolean,
  onChange?: () => void,
): HTMLLabelElement {
  const label = document.createElement('label');
  const box = document.createElement('input');
  box.type = 'checkbox';
  box.value = name;
  box.checked = checked;
  if (onChange) box.addEventListener('change', onChange);
  label.append(box, ` ${name}`);
  return label;
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
  (field('browser') as HTMLInputElement).placeholder = config?.browser_found
    ? `${config.browser_found}`
    : 'no Chrome or Edge found; choose one with Browse…';
  (field('download_dir') as HTMLInputElement).placeholder =
    config?.download_found ?? 'your Downloads folder';
  const chosen = new Set(
    (settings.formats ?? '').split(',').map((f) => f.trim()),
  );
  formatsBox.replaceChildren(
    ...(choices.formats ?? []).map((f) =>
      checkbox(f, chosen.has(f), () => void saveOne('formats')),
    ),
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
    statsNote.textContent = t('statsEmpty');
    return;
  }
  statsNote.textContent = `${stats.runs} · ${t('statsHelp')}`;
  const measure = (name: string, m: Measure): string[] => [
    name,
    String(m.runs),
    formatSeconds(m.seconds),
    `${m.input}+${m.output}`,
    m.tokens_per_second ? m.tokens_per_second.toFixed(1) : '',
    m.usd ? m.usd.toFixed(3) : '0',
  ];
  statsBox.replaceChildren(
    table(
      [t('colStep'), t('colMedian')],
      STEPS.filter((s) => s in stats.steps).map((s) => [
        t(STEP_KEY[s] ?? s),
        formatSeconds(stats.steps[s]),
      ]),
    ),
    table(
      [
        t('colModel'),
        t('colRuns'),
        t('colSummarise'),
        t('colTokensPerVideo'),
        t('colTokensPerSecond'),
        t('colUsd'),
      ],
      Object.entries(stats.models).map(([name, m]) => measure(name, m)),
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

// What the chosen backend accepts as `model`, for the field's list and
// for the benchmark's checkboxes.
async function loadModels(): Promise<void> {
  const backend = field('llm').value;
  if (!connected) {
    modelHint.textContent = t('statsConnect');
    return;
  }
  try {
    const { models } = await request<{ models: string[] }>(
      connection(),
      'GET',
      `/models?llm=${encodeURIComponent(backend)}`,
    );
    modelList.replaceChildren(...models.map((m) => new Option(m)));
    modelHint.textContent = `${models.length} · ${backend}`;
    benchModels.replaceChildren(
      ...models.map((m) => checkbox(m, m === field('model').value)),
    );
  } catch (error) {
    modelList.replaceChildren();
    benchModels.replaceChildren();
    modelHint.textContent = message(error);
  }
}

function light(id: string, name: string, state?: Light): void {
  const item = pick<HTMLElement>(`#light-${id}`);
  item.className = `light ${state ? (state.ok ? 'ok' : 'bad') : 'unknown'}`;
  item.textContent = `${name}: ${state?.detail ?? t('notChecked')}`;
}

async function loadHealth(): Promise<void> {
  try {
    const health = await request<Health>(connection(), 'GET', '/health');
    light('service', t('lightService'), health.service);
    light('llm', t('lightLlm'), health.llm);
    light('stt', t('lightStt'), health.stt);
    light('capabilities', t('lightCapabilities'), health.capabilities);
  } catch (error) {
    light('service', t('lightService'), { ok: false, detail: message(error) });
    light('llm', t('lightLlm'));
    light('stt', t('lightStt'));
    light('capabilities', t('lightCapabilities'));
  }
}

async function loadService(): Promise<void> {
  try {
    config = await request<Config>(connection(), 'GET', '/config');
    connected = true;
    noService.hidden = true;
    show();
    serviceStatus.textContent = `${config.version} · ${config.home} · ${config.log}`;
    showStats(await request<Stats>(connection(), 'GET', '/stats'));
  } catch (error) {
    connected = false;
    config = undefined;
    show();
    noService.hidden = !(error instanceof NoServiceError);
    serviceStatus.textContent = `${t('notConnected')} ${message(error)}`;
    statsNote.textContent = t('statsConnect');
  }
  await Promise.all([loadModels(), loadHealth()]);
}

function values(): Record<string, string> {
  const out: Record<string, string> = {};
  for (const key of Object.keys(FIELDS)) out[key] = field(key).value.trim();
  out.formats = Array.from(
    formatsBox.querySelectorAll<HTMLInputElement>('input:checked'),
    (box) => box.value,
  ).join(',');
  return out;
}

// Saved when a field is left, not only on the button: the owner asked
// for it, and a lost setting is worse than a request too many. A key
// the service showed as stars goes back as stars, which the service
// reads as "keep it".
async function saveOne(key: string): Promise<void> {
  if (!connected) {
    say(t('notConnected'));
    return;
  }
  const all = values();
  try {
    await request(connection(), 'PUT', '/config', { [key]: all[key] });
    say(t('saved'));
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
  translate();
  pick<HTMLElement>('#start-command').textContent = t('noServiceCommand');
  const stored = await api.storage.local.get({
    blocklist: DEFAULT_BLOCKLIST,
    seen: [] as string[],
    ...DEFAULT_CONNECTION,
  });
  blocklistBox.value = (stored.blocklist as string[]).join('\n');
  const seen = stored.seen as string[];
  seenBox.value = seen.join('\n');
  seenCount.textContent = t('seenCount', String(seen.length));
  serviceUrlBox.value = stored.serviceUrl as string;
  tokenBox.value = stored.token as string;
  await loadService();
}

// Every field saves itself when it is left; a select saves on change.
for (const key of Object.keys(FIELDS)) {
  const element = field(key);
  const event = element instanceof HTMLSelectElement ? 'change' : 'blur';
  element.addEventListener(event, () => {
    void saveOne(key);
    if (key === 'llm') {
      showBackendFields();
      void loadModels();
    }
    if (key === 'stt') showBackendFields();
  });
}

pick('#connect').addEventListener('click', async () => {
  await api.storage.local.set(connection());
  await loadService();
});
pick('#copy-command').addEventListener('click', async () => {
  await navigator.clipboard.writeText(t('noServiceCommand'));
  say(t('copied'));
});

// A file or folder dialog on the desktop, opened by the service: the
// browser's own dialog never tells an extension the full path.
async function browse(key: string, kind: 'file' | 'folder'): Promise<void> {
  const box = field(key) as HTMLInputElement;
  try {
    const { path } = await request<{ path: string }>(
      connection(),
      'POST',
      '/pick',
      { kind, start: box.value.trim() },
    );
    if (path) {
      box.value = path;
      await saveOne(key);
    }
  } catch (error) {
    say(message(error));
  }
}

pick('#pick-vault').addEventListener('click', () => {
  void browse('obsidian_vault', 'folder');
});
pick('#pick-download').addEventListener('click', () => {
  void browse('download_dir', 'folder');
});
pick('#pick-browser').addEventListener('click', () => {
  void browse('browser', 'file');
});
pick('#pick-template').addEventListener('click', () => {
  void browse('pdf_template', 'file');
});

// The benchmark: the same video through the ticked models, then a table
// of what each took.
function showBench(rows: BenchRow[]): void {
  benchResult.replaceChildren(
    table(
      [
        t('colModel'),
        t('colRuns'),
        t('colSummarise'),
        t('colTokensPerVideo'),
        t('colTokensPerSecond'),
      ],
      rows.map((row) => [
        row.model,
        String(row.run),
        row.error ? row.error : formatSeconds(row.seconds),
        `${row.input}+${row.output}`,
        row.tokens_per_second ? row.tokens_per_second.toFixed(1) : '',
      ]),
    ),
  );
}

pick('#bench-start').addEventListener('click', async () => {
  const models = Array.from(
    benchModels.querySelectorAll<HTMLInputElement>('input:checked'),
    (box) => box.value,
  );
  const url = pick<HTMLInputElement>('#bench-url').value.trim();
  if (!url || models.length === 0) {
    benchStatus.textContent = `${t('benchUrl')} · ${t('benchModels')}`;
    return;
  }
  benchStatus.textContent = t('benchRunning');
  try {
    const job = await request<Job & { bench?: BenchRow[] }>(
      connection(),
      'POST',
      '/bench',
      {
        url,
        models,
        repeat: Number(pick<HTMLInputElement>('#bench-repeat').value) || 1,
      },
    );
    const timer = setInterval(async () => {
      const now = await request<Job & { bench?: BenchRow[] }>(
        connection(),
        'GET',
        `/jobs/${job.id}`,
      );
      if (now.bench) showBench(now.bench);
      if (now.status !== 'queued' && now.status !== 'running') {
        clearInterval(timer);
        benchStatus.textContent = t(now.status);
      }
    }, 3000);
  } catch (error) {
    benchStatus.textContent = message(error);
  }
});

pick('#save').addEventListener('click', async () => {
  const blocklist = blocklistBox.value
    .split('\n')
    .map((line) => line.trim().toLowerCase())
    .filter((line) => line.length > 0);
  await api.storage.local.set({ blocklist, ...connection() });
  if (!connected) {
    say(t('notConnected'));
    return;
  }
  try {
    await request(connection(), 'PUT', '/config', values());
    await loadHealth();
    say(t('saved'));
  } catch (error) {
    say(message(error));
  }
});

pick('#clear').addEventListener('click', async () => {
  await api.storage.local.set({ seen: [] });
  await load();
  say(t('forgotten'));
});

void load();
