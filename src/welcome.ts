// The page a fresh install opens once. The store hands over the
// extension and nothing else, so the service is still missing at this
// point; the popup's "start it with video-tldr serve" would send the
// user to a command that does not exist yet. Here are the ways to get
// it, and the choice is the user's.
import { api } from './api.js';
import { t, translate } from './i18n.js';

// Kept next to each other on purpose: these three lines also stand in
// README.md, and a reader who compares them should find the same text.
//
// No winget: it installs artefacts (msi, exe, msix, a portable zip), and
// this is a wheel that uv unpacks into an environment with gigabytes of
// CUDA in it. uv itself is in winget because it is one binary.
const COMMANDS: Record<string, string> = {
  'cmd-script':
    'irm https://raw.githubusercontent.com/corgan2222/video-tldr/main/install.ps1 | iex',
  'cmd-uv': 'uv tool install video-tldr',
  'cmd-source': 'git clone https://github.com/corgan2222/video-tldr.git',
};

function say(text: string): void {
  const status = document.querySelector<HTMLElement>('#status');
  if (!status) return;
  status.textContent = text;
  status.className = 'status ok';
  setTimeout(() => {
    status.textContent = '';
  }, 4000);
}

translate();
for (const [id, command] of Object.entries(COMMANDS)) {
  const box = document.querySelector<HTMLElement>(`#${id}`);
  if (box) box.textContent = command;
}
document
  .querySelectorAll<HTMLButtonElement>('[data-copy]')
  .forEach((button) => {
    button.addEventListener('click', async () => {
      const id = button.dataset.copy;
      if (!id) return;
      await navigator.clipboard.writeText(COMMANDS[id]);
      say(t('copied'));
    });
  });
document.querySelector('#to-settings')?.addEventListener('click', (event) => {
  event.preventDefault();
  void api.runtime.openOptionsPage();
});
