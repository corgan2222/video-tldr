import { readFileSync } from 'node:fs';
import { expect, it } from 'vitest';

const version = (path: string): string =>
  JSON.parse(readFileSync(path, 'utf8')).version;

// scripts/bump_version.py writes both files. The stores read the manifest,
// npm and the release workflow read package.json; a number that moves in one
// place only ships a mislabelled build.
it('package.json and src/manifest.json carry the same version', () => {
  expect(version('src/manifest.json')).toBe(version('package.json'));
});
