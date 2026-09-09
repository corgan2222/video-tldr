import { api } from './api.js';
import { DEFAULT_BLOCKLIST } from './links.js';

const blocklistBox = document.querySelector<HTMLTextAreaElement>('#blocklist')!;
const seenBox = document.querySelector<HTMLTextAreaElement>('#seen')!;
const seenCount = document.querySelector<HTMLElement>('#seen-count')!;
const status = document.querySelector<HTMLElement>('#status')!;

async function load(): Promise<void> {
  const stored = await api.storage.local.get({
    blocklist: DEFAULT_BLOCKLIST,
    seen: [] as string[],
  });
  blocklistBox.value = (stored.blocklist as string[]).join('\n');
  const seen = stored.seen as string[];
  seenBox.value = seen.join('\n');
  seenCount.textContent = `${seen.length} links`;
}

function say(text: string): void {
  status.textContent = text;
  setTimeout(() => {
    status.textContent = '';
  }, 2000);
}

document.querySelector('#save')!.addEventListener('click', async () => {
  const blocklist = blocklistBox.value
    .split('\n')
    .map((line) => line.trim().toLowerCase())
    .filter((line) => line.length > 0);
  await api.storage.local.set({ blocklist });
  say('Saved.');
});

document.querySelector('#clear')!.addEventListener('click', async () => {
  await api.storage.local.set({ seen: [] });
  await load();
  say('Forgotten.');
});

void load();
