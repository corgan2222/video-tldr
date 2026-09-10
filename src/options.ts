import { api } from './api.js';
import { DEFAULT_BLOCKLIST } from './links.js';
import {
  DEFAULT_CONNECTION,
  request,
  type Config,
  type Connection,
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
const serviceSettings = pick<HTMLFieldSetElement>('#service-settings');
const formatsBox = pick<HTMLElement>('#formats');
const modelList = pick<HTMLDataListElement>('#models');
const modelHint = pick<HTMLElement>('#model-hint');

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

// The choice between fast and accurate, as `corganshelper models stt`
// prints it: speed class, leaderboard word error rate, languages.
function sttLabel(config: Config, name: string): string {
  const spec = config.stt_models[name];
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

// What the chosen backend accepts as `model`, for the field's list; a
// backend that needs a key or a running server says so in the hint.
async function loadModels(): Promise<void> {
  const backend = field('llm').value;
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

async function loadService(): Promise<void> {
  try {
    const config = await request<Config>(connection(), 'GET', '/config');
    for (const key of Object.keys(FIELDS)) {
      const element = field(key);
      const value = config.settings[key] ?? '';
      if (element instanceof HTMLSelectElement) {
        fillSelect(
          element,
          config.choices[key] ?? [],
          value,
          key === 'stt' ? (c) => sttLabel(config, c) : undefined,
        );
      } else {
        element.value = value;
      }
    }
    const chosen = new Set(
      (config.settings.formats ?? '').split(',').map((f) => f.trim()),
    );
    formatsBox.replaceChildren(
      ...(config.choices.formats ?? []).map((f) => checkbox(f, chosen.has(f))),
    );
    serviceStatus.textContent = `Connected to corganshelper ${config.version}, data under ${config.home}.`;
    serviceSettings.disabled = false;
    await loadModels();
  } catch (error) {
    serviceStatus.textContent = message(error);
    serviceSettings.disabled = true;
  }
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

function say(text: string): void {
  status.textContent = text;
  setTimeout(() => {
    status.textContent = '';
  }, 4000);
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
  if (tokenBox.value) await loadService();
}

pick('#connect').addEventListener('click', async () => {
  await api.storage.local.set(connection());
  await loadService();
});

field('llm').addEventListener('change', () => {
  void loadModels();
});

pick('#save').addEventListener('click', async () => {
  const blocklist = blocklistBox.value
    .split('\n')
    .map((line) => line.trim().toLowerCase())
    .filter((line) => line.length > 0);
  await api.storage.local.set({ blocklist, ...connection() });
  if (!serviceSettings.disabled) {
    try {
      await saveService();
    } catch (error) {
      say(message(error));
      return;
    }
  }
  say('Saved.');
});

pick('#clear').addEventListener('click', async () => {
  await api.storage.local.set({ seen: [] });
  await load();
  say('Forgotten.');
});

void load();
