import { readFileSync } from 'node:fs';
import { expect, it } from 'vitest';

const version = (path: string): string =>
  JSON.parse(readFileSync(path, 'utf8')).version;

// scripts/bump_version.py writes all three files. The stores read the
// manifest, npm and the release workflow read package.json, pip reads the
// service's pyproject; a number that moves in one place only ships a
// mislabelled build.
it('package.json and src/manifest.json carry the same version', () => {
  expect(version('src/manifest.json')).toBe(version('package.json'));
});

it('the service package carries the same version as package.json', () => {
  const init = readFileSync(
    'service/src/corganshelper_service/__init__.py',
    'utf8',
  );
  const match = /^__version__ = "([^"]+)"$/m.exec(init);
  expect(match?.[1]).toBe(version('package.json'));
});
