import { readFileSync } from 'node:fs';
import { expect, it } from 'vitest';

const manifest = JSON.parse(readFileSync('src/manifest.json', 'utf8'));

// The Chrome Web Store cuts the listing summary at 132 characters and
// refuses the upload that carries more. Two were spare on 2026-09-10, so
// one added clause is enough to break a release.
it('the description fits what the Chrome Web Store takes', () => {
  expect(manifest.description.length).toBeLessThanOrEqual(132);
});

// A required host permission warns at install time in both stores and
// gives a reviewer something to ask about. The pages ask for it on the
// first click instead; api.ts holds hasAccess and askAccess.
it('the host permission is optional, not required', () => {
  expect(manifest.optional_host_permissions).toContain('http://127.0.0.1/*');
  expect(manifest.host_permissions).toBeUndefined();
});

// Firefox drops a host permission that carries a port, silently, at load
// time; the fetch then fails on CORS while Chrome is fine.
it('no host pattern carries a port', () => {
  for (const pattern of manifest.optional_host_permissions ?? []) {
    expect(pattern).not.toMatch(/:\d+/);
  }
});
