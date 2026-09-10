import { readFileSync } from 'node:fs';
import { it, expect } from 'vitest';

// install.ps1 downloads what release.yml attached, and the two name those
// files independently. A rename on one side alone breaks nothing here and
// nothing in CI: it breaks the first person who runs the installer against
// the next release. So the names are compared, not assumed.
const script = readFileSync('install.ps1', 'utf8');
const workflow = readFileSync('.github/workflows/release.yml', 'utf8');
const pyproject = readFileSync('service/pyproject.toml', 'utf8');

const EXTRAS = ['gpu', 'cpu'];

it('the installer asks for the assets the release workflow attaches', () => {
  const uploaded = workflow.split('gh release upload')[1].split('\n').join(' ');
  expect(uploaded).toContain('overrides.txt');
  expect(script).toContain("'overrides.txt'");
  for (const extra of EXTRAS) {
    expect(uploaded).toContain(`constraints-${extra}.txt`);
  }
  // The script builds the name from the extra it picked.
  expect(script).toContain('"constraints-$chosen.txt"');
  expect(uploaded).toContain('*.whl');
  expect(script).toContain("'*.whl'");
});

it('the installer installs the package pyproject.toml declares', () => {
  const declared = /^name = "(.+)"$/m.exec(pyproject);
  expect(declared).not.toBeNull();
  expect(script).toContain(`$PackageName = '${declared![1]}'`);
});

it('the extras the installer offers are the ones pyproject.toml defines', () => {
  // Up to the next table header, or `conflicts` and `packages` below it
  // would count as extras too.
  const section = pyproject
    .split('[project.optional-dependencies]')[1]
    .split(/^\[/m)[0];
  const defined = [...section.matchAll(/^(\w+) = \[/gm)].map((m) => m[1]);
  expect(defined.sort()).toEqual([...EXTRAS].sort());
  for (const extra of EXTRAS) {
    expect(script).toContain(`'${extra}'`);
  }
});
