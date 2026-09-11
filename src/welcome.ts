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
  'cmd-uv': 'uv tool install video-tldr-service',
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
// Two overlapping sheets, the sign every editor uses for copy. Drawn
// here rather than three times in the HTML, and with a label, because an
// icon on its own says nothing to a screen reader.
function copyIcon(): SVGElement {
  const ns = 'http://www.w3.org/2000/svg';
  const svg = document.createElementNS(ns, 'svg');
  svg.setAttribute('viewBox', '0 0 24 24');
  svg.setAttribute('aria-hidden', 'true');
  const back = document.createElementNS(ns, 'rect');
  back.setAttribute('x', '9');
  back.setAttribute('y', '9');
  back.setAttribute('width', '11');
  back.setAttribute('height', '11');
  back.setAttribute('rx', '2');
  const front = document.createElementNS(ns, 'path');
  front.setAttribute(
    'd',
    'M5 15H4a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1h10a1 1 0 0 1 1 1v1',
  );
  svg.append(back, front);
  return svg;
}

document
  .querySelectorAll<HTMLButtonElement>('[data-copy]')
  .forEach((button) => {
    button.append(copyIcon());
    button.title = t('copyCommand');
    button.setAttribute('aria-label', t('copyCommand'));
    button.addEventListener('click', async () => {
      const id = button.dataset.copy;
      if (!id) return;
      await navigator.clipboard.writeText(COMMANDS[id]);
      say(t('copied'));
    });
  });
const manual = document.querySelector<HTMLAnchorElement>('#to-manual');
if (manual) manual.href = t('welcomeManualUrl');

document.querySelector('#to-settings')?.addEventListener('click', (event) => {
  event.preventDefault();
  void api.runtime.openOptionsPage();
});
