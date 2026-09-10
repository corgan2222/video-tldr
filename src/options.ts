import { api } from './api.js';
import { t, translate } from './i18n.js';
import { DEFAULT_BLOCKLIST } from './links.js';
import {
  BACKEND_FIELDS,
  BACKEND_HELP,
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
const modelChoice = pick<HTMLSelectElement>('#model-choice');
const modelBox = pick<HTMLInputElement>('#model');
const modelHint = pick<HTMLElement>('#model-hint');
const backendInfo = pick<HTMLElement>('#backend-info');
const statsBox = pick<HTMLElement>('#stats');
const statsNote = pick<HTMLElement>('#stats-note');
const benchModels = pick<HTMLElement>('#bench-models');
const benchStatus = pick<HTMLElement>('#bench-status');
const benchResult = pick<HTMLElement>('#bench-result');
const checkResult = pick<HTMLElement>('#check-result');

// Every key of config.json this page edits, by element. A select takes
// its choices from the service, so a value added there shows up here
// without a release of the extension.
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

// The two entries the model list carries besides the models themselves.
const DEFAULT_MODEL = '';
const CUSTOM_MODEL = '\u0000custom';

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
  if (!spec) return name;
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
  label.append(box, document.createTextNode(name));
  return label;
}

// The backend decides which extra fields make sense; the OpenAI key and
// address also serve the openai transcriber, so they show for it too.
function showBackendFields(): void {
  const backend = field('llm').value;
  const needed = new Set(BACKEND_FIELDS[backend] ?? []);
  if (field('stt').value === 'openai') {
    needed.add('openai_api_key');
    needed.add('openai_base_url');
  }
  document.querySelectorAll<HTMLElement>('[data-field]').forEach((box) => {
    box.hidden = !needed.has(box.dataset.field ?? '');
  });
  const recommended = config?.default_models[backend] ?? '';
  backendInfo.textContent =
    t(BACKEND_HELP[backend] ?? '') +
    (recommended ? ` (${t('modelDefault')}: ${recommended})` : '');
}

// A select, not a text field with a list: a datalist only offers what
// matches what is typed, so a stored name hid every other model until
// the field was cleared by hand. The last entry opens the text field for
// a name the server does not list.
function showModelChoice(models: string[]): void {
  const stored = modelBox.value;
  const known = models.includes(stored);
  const options = [
    new Option(
      `${t('modelDefault')}${config?.default_models[field('llm').value] ? ` (${config.default_models[field('llm').value]})` : ''}`,
      DEFAULT_MODEL,
    ),
    ...models.map((m) => new Option(m, m)),
    new Option(t('modelCustom'), CUSTOM_MODEL),
  ];
  if (stored && !known) options.splice(1, 0, new Option(stored, stored));
  modelChoice.replaceChildren(...options);
  modelChoice.value = stored || DEFAULT_MODEL;
  modelBox.hidden = true;
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
  (field('browser') as HTMLInputElement).placeholder =
    config?.browser_found || t('browserHelp');
  (field('download_dir') as HTMLInputElement).placeholder =
    config?.download_found ?? '';
  const chosen = new Set(
    (settings.formats ?? '').split(',').map((f) => f.trim()),
  );
  formatsBox.replaceChildren(
    ...(choices.formats ?? []).map((f) =>
      checkbox(f, chosen.has(f), () => void saveOne('formats')),
    ),
  );
  showModelChoice([]);
  showBackendFields();
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

// Three small tables from GET /stats: the steps, the language models,
// the transcribers, each with what it took on this machine.
function showStats(stats: Stats): void {
  if (stats.runs === 0) {
    statsBox.replaceChildren();
    statsNote.textContent = t('statsEmpty');
    return;
  }
  statsNote.textContent = `${stats.runs} · ${t('historyHelp')}`;
  const measure = (name: string, m: Measure): string[] => [
    name,
    String(m.runs),
    formatSeconds(m.seconds),
    `${m.input}+${m.output}`,
    m.tokens_per_second ? m.tokens_per_second.toFixed(1) : '–',
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

// What the chosen backend accepts as `model`, for the select and for the
// benchmark's checkboxes.
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
    showModelChoice(models);
    modelHint.textContent = `${models.length} · ${backend}`;
    benchModels.replaceChildren(
      ...models.map((m) => checkbox(m, m === modelBox.value)),
    );
  } catch (error) {
    showModelChoice([]);
    benchModels.replaceChildren();
    modelHint.textContent = message(error);
  }
}

// `soft` turns a failed light amber instead of red: a model that answers
// and cannot read pictures still gets the run done, only without labels.
function light(id: string, name: string, state?: Light, soft = false): void {
  const item = pick<HTMLElement>(`#light-${id}`);
  const trouble = soft ? 'warn' : 'bad';
  item.className = `light ${state ? (state.ok ? 'ok' : trouble) : 'unknown'}`;
  const what = document.createElement('span');
  what.className = 'what';
  what.textContent = `${name}:`;
  const detail = document.createElement('span');
  detail.className = 'detail';
  detail.textContent = state?.detail ?? t('notChecked');
  item.replaceChildren(what, detail);
}

async function loadHealth(): Promise<Health | undefined> {
  try {
    const health = await request<Health>(connection(), 'GET', '/health');
    light('service', t('lightService'), health.service);
    light('llm', t('lightLlm'), health.llm);
    light('stt', t('lightStt'), health.stt);
    light('capabilities', t('lightCapabilities'), health.capabilities, true);
    return health;
  } catch (error) {
    light('service', t('lightService'), { ok: false, detail: message(error) });
    light('llm', t('lightLlm'));
    light('stt', t('lightStt'));
    light('capabilities', t('lightCapabilities'));
    checkResult.textContent = message(error);
    checkResult.className = 'status bad';
    return undefined;
  }
}

// Ask the backend now, with what stands in the fields, instead of finding
// out in the middle of a run: the service answers `GET /health` by asking
// the server for its models, which a refused key fails.
async function checkBackend(): Promise<void> {
  checkResult.textContent = t('checking');
  checkResult.className = 'status';
  const backend = field('llm').value;
  for (const key of ['llm', 'model', ...(BACKEND_FIELDS[backend] ?? [])]) {
    await saveOne(key);
  }
  const [, health] = await Promise.all([loadModels(), loadHealth()]);
  if (!health) return;
  // Three answers, three colours: green when everything works, amber when
  // the model answers but cannot do all of it, red when nothing gets
  // through at all.
  const able = health.capabilities;
  const limited = Boolean(able && !able.ok);
  checkResult.textContent = limited ? able!.detail : health.llm.detail;
  checkResult.className = !health.llm.ok
    ? 'status bad'
    : limited
      ? 'status warn'
      : 'status ok';
}

async function loadService(): Promise<void> {
  try {
    config = await request<Config>(connection(), 'GET', '/config');
    connected = true;
    noService.hidden = true;
    show();
    serviceStatus.textContent = `${config.version} · ${config.home}`;
    serviceStatus.className = 'status ok';
    showStats(await request<Stats>(connection(), 'GET', '/stats'));
  } catch (error) {
    connected = false;
    config = undefined;
    show();
    noService.hidden = !(error instanceof NoServiceError);
    serviceStatus.textContent = `${t('notConnected')} ${message(error)}`;
    serviceStatus.className = 'status bad';
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

// Saved when a field is left, not only on the button: a lost setting is
// worse than a request too many. A key the service showed as stars goes
// back as stars, which the service reads as "keep it".
async function saveOne(key: string): Promise<void> {
  if (!connected) {
    say(t('notConnected'), true);
    return;
  }
  try {
    await request(connection(), 'PUT', '/config', { [key]: values()[key] });
    say(t('saved'));
  } catch (error) {
    say(message(error), true);
  }
}

// Saved, copied, forgotten: what worked is green, what did not is red.
function say(text: string, bad = false): void {
  status.textContent = text;
  status.className = bad ? 'status bad' : 'status ok';
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

// What the language model hangs on: a change to one of these makes the
// lights stale, so they are asked again right away.
const MODEL_FIELDS = new Set([
  'llm',
  'model',
  ...Object.values(BACKEND_FIELDS).flat(),
]);

// Every field saves itself when it is left; a select saves on change.
for (const key of Object.keys(FIELDS)) {
  const element = field(key);
  const event = element instanceof HTMLSelectElement ? 'change' : 'blur';
  element.addEventListener(event, () => {
    void saveOne(key).then(() => {
      if (key === 'llm') void loadModels();
      // After the save, never before it: the service reads the stored
      // values, so a key checked too early is the one from yesterday.
      if (MODEL_FIELDS.has(key)) void loadHealth();
    });
    if (key === 'llm' || key === 'stt') showBackendFields();
  });
}

pick('#check-backend').addEventListener('click', () => void checkBackend());

// The model select writes into the hidden field the settings read; the
// last entry hands over to that field for a name the server does not
// list.
modelChoice.addEventListener('change', () => {
  if (modelChoice.value === CUSTOM_MODEL) {
    modelBox.hidden = false;
    modelBox.focus();
    return;
  }
  modelBox.hidden = true;
  modelBox.value = modelChoice.value;
  void saveOne('model');
  void loadHealth();
});

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
    say(message(error), true);
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
        row.tokens_per_second ? row.tokens_per_second.toFixed(1) : '–',
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
    say(t('notConnected'), true);
    return;
  }
  try {
    await request(connection(), 'PUT', '/config', values());
    await loadHealth();
    say(t('saved'));
  } catch (error) {
    say(message(error), true);
  }
});

pick('#clear').addEventListener('click', async () => {
  await api.storage.local.set({ seen: [] });
  await load();
  say(t('forgotten'));
});

void load();
