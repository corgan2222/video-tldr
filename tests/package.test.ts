import { readFileSync } from 'node:fs';
import { expect, it } from 'vitest';

// One source tree, three stores. scripts/package.py strips the manifest of
// what the target store does not read, by dotted key name, as text. Rename
// a key in the manifest and the strip quietly removes nothing: Firefox
// would ship a service_worker it ignores, Chrome a background.scripts it
// calls an unrecognised key, and both reviews start with a warning. The
// build stays green either way, so the two files are compared here.
const manifest = JSON.parse(readFileSync('src/manifest.json', 'utf8'));
const script = readFileSync('scripts/package.py', 'utf8');
const release = readFileSync('.github/workflows/release.yml', 'utf8');

// The DROP table, read back out of the script: target -> dotted keys.
function dropTable(): Record<string, string[]> {
  const body = script.split('DROP: dict[str, tuple[str, ...]] = {')[1];
  expect(body, 'scripts/package.py has no DROP table').toBeDefined();
  const table: Record<string, string[]> = {};
  for (const line of body.split('}')[0].split('\n')) {
    const entry = /^\s*"(\w+)":\s*\((.*)\),?\s*$/.exec(line);
    if (!entry) continue;
    table[entry[1]] = [...entry[2].matchAll(/"([^"]+)"/g)].map((m) => m[1]);
  }
  return table;
}

function at(path: string): unknown {
  return path
    .split('.')
    .reduce<unknown>(
      (node, key) =>
        node && typeof node === 'object'
          ? (node as Record<string, unknown>)[key]
          : undefined,
      manifest,
    );
}

const table = dropTable();

it('every key the packer strips exists in the manifest', () => {
  expect(Object.keys(table)).toEqual(['firefox', 'chrome', 'edge']);
  for (const [target, keys] of Object.entries(table)) {
    expect(keys.length, `${target} strips nothing`).toBeGreaterThan(0);
    for (const key of keys) {
      expect(
        at(key),
        `${target} strips ${key}, which is not in the manifest`,
      ).toBeDefined();
    }
  }
});

it('each store keeps the background key it reads', () => {
  // Firefox reads scripts, Chromium reads service_worker. Neither may end
  // up on the list of what its own package loses.
  expect(table.firefox).not.toContain('background.scripts');
  expect(table.chrome).not.toContain('background.service_worker');
  expect(table.edge).not.toContain('background.service_worker');
  expect(at('background.scripts')).toBeDefined();
  expect(at('background.service_worker')).toBeDefined();
});

it('the release attaches one package per target', () => {
  const uploaded = release.split('gh release upload')[1] ?? '';
  for (const target of Object.keys(table)) {
    expect(uploaded, `the release uploads no ${target} package`).toContain(
      target,
    );
  }
});
