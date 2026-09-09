// The logic behind "Open all links", without a browser API in sight: vitest
// runs it as it is, and background.ts feeds it what the page handed over.

// Sponsor and affiliate hosts the owner never wants opened, plus YouTube
// itself, whose links in a description point back at more videos. A host
// matches when it equals an entry or ends in "." + entry.
export const DEFAULT_BLOCKLIST = [
  'youtube.com',
  'youtu.be',
  'amzn.to',
  'amazon.com',
  'amazon.de',
  'patreon.com',
  'ko-fi.com',
  'buymeacoffee.com',
  'paypal.me',
  'paypal.com',
  // Ad click-through hosts: a "select all" on a watch page sweeps them in.
  'googleadservices.com',
  'doubleclick.net',
];

const REDIRECT_HOPS = 3;

// YouTube wraps every description link as youtube.com/redirect?q=<target>,
// Google search does the same as google.com/url?q=. Without unwrapping,
// the blocklist would swallow every link on a watch page.
export function unwrapRedirect(raw: string, hops = REDIRECT_HOPS): string {
  let url: URL;
  try {
    url = new URL(raw);
  } catch {
    return raw;
  }
  const host = url.hostname.toLowerCase();
  const viaYouTube =
    /(^|\.)youtube\.com$/.test(host) && url.pathname === '/redirect';
  const viaGoogle =
    /(^|\.)google\.[a-z.]+$/.test(host) && url.pathname === '/url';
  if (!viaYouTube && !viaGoogle) return raw;
  const target = url.searchParams.get('q') ?? url.searchParams.get('url');
  if (!target || hops === 0) return raw;
  return unwrapRedirect(target, hops - 1);
}

// The same page linked twice must count once: lower-case host, no fragment,
// no tracking parameters, no trailing slash. Anything that is not http(s)
// (mailto:, javascript:) is dropped.
export function normalize(raw: string): string | null {
  let url: URL;
  try {
    url = new URL(raw);
  } catch {
    return null;
  }
  if (url.protocol !== 'http:' && url.protocol !== 'https:') return null;
  url.hash = '';
  for (const key of [...url.searchParams.keys()]) {
    if (/^utm_/i.test(key) || key === 'fbclid' || key === 'gclid') {
      url.searchParams.delete(key);
    }
  }
  url.hostname = url.hostname.toLowerCase();
  url.pathname = url.pathname.replace(/\/+$/, '') || '/';
  return url.toString();
}

export function isBlocked(url: string, blocklist: string[]): boolean {
  const host = new URL(url).hostname;
  return blocklist.some(
    (entry) => host === entry || host.endsWith('.' + entry),
  );
}

// Selected text carries URLs only as visible characters. YouTube shortens
// long ones with an ellipsis, and a shortened URL opens a 404, so anything
// ending in "…" or "..." is skipped; the anchors carry the full form anyway.
const URL_IN_TEXT = /https?:\/\/[^\s<>"'\])]+/g;

export function extractFromText(text: string): string[] {
  const found = text.match(URL_IN_TEXT) ?? [];
  return found
    .filter((u) => !/(…|\.\.\.)$/.test(u))
    .map((u) => u.replace(/[.,;:!?]+$/, ''));
}

export interface Selection {
  hrefs: string[];
  text: string;
}

export interface Plan {
  open: string[];
  blocked: number;
  known: number;
}

export function planOpen(
  selection: Selection,
  blocklist: string[],
  seen: Set<string>,
): Plan {
  const candidates = [...selection.hrefs, ...extractFromText(selection.text)];
  const done = new Set<string>();
  const plan: Plan = { open: [], blocked: 0, known: 0 };
  for (const raw of candidates) {
    const url = normalize(unwrapRedirect(raw));
    if (!url || done.has(url)) continue;
    done.add(url);
    if (isBlocked(url, blocklist)) {
      plan.blocked += 1;
    } else if (seen.has(url)) {
      plan.known += 1;
    } else {
      plan.open.push(url);
    }
  }
  return plan;
}
