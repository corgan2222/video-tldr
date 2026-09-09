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
const serviceSettings = pick<HTMLElement>('#service-settings');
// The choices come from the service, so a backend added there shows up
// here without a release of the extension.
const selects: Record<string, HTMLSelectElement> = {
  llm: pick('#llm'),
  stt: pick('#stt'),
  language: pick('#language'),
};
const modelBox = pick<HTMLInputElement>('#model');
const vaultBox = pick<HTMLInputElement>('#obsidian-vault');
const formatsBox = pick<HTMLElement>('#formats');

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
): void {
  select.replaceChildren(...choices.map((c) => new Option(c, c)));
  select.value = value;
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

async function loadService(): Promise<void> {
  try {
    const config = await request<Config>(connection(), 'GET', '/config');
    for (const [key, select] of Object.entries(selects)) {
      fillSelect(select, config.choices[key] ?? [], config.settings[key] ?? '');
    }
    modelBox.value = config.settings.model ?? '';
    vaultBox.value = config.settings.obsidian_vault ?? '';
    const chosen = new Set(
      (config.settings.formats ?? '').split(',').map((f) => f.trim()),
    );
    formatsBox.replaceChildren(
      ...(config.choices.formats ?? []).map((f) => checkbox(f, chosen.has(f))),
    );
    serviceStatus.textContent = `Connected to corganshelper ${config.version}, data under ${config.home}.`;
    serviceSettings.hidden = false;
  } catch (error) {
    serviceStatus.textContent =
      error instanceof Error ? error.message : String(error);
    serviceSettings.hidden = true;
  }
}

// Only the fields this page shows go back; the service keeps the rest of
// config.json (the keys, the URLs of the local servers) as it is.
async function saveService(): Promise<void> {
  const formats = Array.from(
    formatsBox.querySelectorAll<HTMLInputElement>('input:checked'),
    (box) => box.value,
  ).join(',');
  await request(connection(), 'PUT', '/config', {
    llm: selects.llm.value,
    stt: selects.stt.value,
    language: selects.language.value,
    model: modelBox.value.trim(),
    obsidian_vault: vaultBox.value.trim(),
    formats,
  });
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

pick('#save').addEventListener('click', async () => {
  const blocklist = blocklistBox.value
    .split('\n')
    .map((line) => line.trim().toLowerCase())
    .filter((line) => line.length > 0);
  await api.storage.local.set({ blocklist, ...connection() });
  if (!serviceSettings.hidden) {
    try {
      await saveService();
    } catch (error) {
      say(error instanceof Error ? error.message : String(error));
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
