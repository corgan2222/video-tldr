import { readFileSync } from 'node:fs';
import { expect, it } from 'vitest';

const version = (path: string): string =>
  JSON.parse(readFileSync(path, 'utf8')).version;

const bump = readFileSync('scripts/bump_version.py', 'utf8');

// scripts/bump_version.py writes all three files. The stores read the
// manifest, npm and the release workflow read package.json, pip reads the
// service's pyproject; a number that moves in one place only ships a
// mislabelled build.
it('package.json and src/manifest.json carry the same version', () => {
  expect(version('src/manifest.json')).toBe(version('package.json'));
});

// has_tags() in the bump script reads local tags only, which is a choice and
// not an oversight: a remote call per commit is the alternative. The price is a
// precondition, a clone that carries the tags. A shallow one reads "no release
// yet" and would raise the patch number again after the first release, so the
// script stops there. The CI job that runs this file sets up Node and no
// Python, so the guard is read from the source instead of being run: what is
// checked is that it stands ahead of the tag read and ends the script.
it('the bump script stops instead of judging tags in a shallow clone', () => {
  const body = bump.split('def has_tags(')[1].split('\ndef ')[0];
  const guard = body.indexOf('--is-shallow-repository');
  expect(guard).toBeGreaterThan(-1);
  expect(body.indexOf('"git", "tag", "--list"')).toBeGreaterThan(guard);
  expect(body).toMatch(/raise SystemExit/);
  // The abort has to name the way out, or it is a dead end.
  expect(body).toContain('--unshallow');
});

// --force promises a bump whatever the tags say, and has_tags() ends the
// script in a shallow clone. Python reads an `and` left to right, so the order
// of those two is what decides whether the promise holds: with has_tags() on
// the left, its SystemExit reaches the one caller that asked not to be stopped.
it('--force is read before the tags are', () => {
  expect(bump).toContain('if not args.force and has_tags(root):');
});

// pre-commit runs the hooks of a stage in file order, and bump-version stages
// the raised patch number it writes. A hook that fails after it leaves that
// number staged for a commit that never happens, and the next attempt raises
// it again. Two arrangements keep that from happening: bump-version comes last
// in the file, and every commit-stage hook ahead of it carries
// `fail_fast: true`, a key the config carries per hook rather than at the top
// level and about which it says itself that nothing fails when it is
// forgotten.
//
// The hooks are counted by their indentation rather than by their first key:
// `- name:` with the `id:` on the next line is the same hook to pre-commit,
// and YAML promises no key order. Each `- ` on the indentation of a `hooks:`
// list opens a block, and the block's `id:` stands somewhere inside it.
//
// Where reading it as text ends (2026-09-10): a `hooks:` list in flow style,
// or a block scalar holding a line that looks like a key on hook indentation,
// is read wrong. Neither is in the file, and package.json carries no YAML
// parser to do better with.
interface Hook {
  id: string | null;
  text: string;
}

const hooks = (config: string): Hook[] => {
  const blocks: Hook[] = [];
  let list: number | null = null; // indentation of the `hooks:` key
  let item: number | null = null; // indentation of a `- ` that opens a hook
  for (const line of config.split('\n')) {
    // A comment carries anything, a `- id:` of its own included.
    if (!line.trim() || /^\s*#/.test(line)) continue;
    const indent = line.search(/\S/);
    if (/^\s*hooks:\s*$/.test(line)) {
      list = indent;
      item = null;
      continue;
    }
    if (list === null) continue;
    // Back at or left of the `hooks:` key: the list ended.
    if (indent <= list) {
      list = null;
      continue;
    }
    if (/^\s*-\s/.test(line) && (item === null || indent === item)) {
      item = indent;
      blocks.push({ id: null, text: '' });
    }
    // A key before the first `- ` belongs to no hook.
    if (!blocks.length) continue;
    blocks[blocks.length - 1].text += `${line}\n`;
  }
  for (const hook of blocks) {
    hook.id = /^\s*(?:-\s+)?id:\s*(\S+)\s*$/m.exec(hook.text)?.[1] ?? null;
  }
  return blocks;
};

// The stages a hook names, or null for a hook that names none and therefore
// runs at every stage. Both spellings count: `stages: [pre-commit]` and a
// block list under the key.
const stagesOf = (hook: Hook): string[] | null => {
  const lines = hook.text.split('\n');
  const at = lines.findIndex((line) => /^\s*(?:-\s+)?stages:/.test(line));
  if (at < 0) return null;
  const inline = lines[at].replace(/^\s*(?:-\s+)?stages:\s*/, '');
  if (inline) return [...inline.matchAll(/[\w-]+/g)].map((m) => m[0]);
  const named: string[] = [];
  for (const line of lines.slice(at + 1)) {
    const entry = /^\s*-\s*([\w-]+)\s*$/.exec(line);
    if (!entry) break;
    named.push(entry[1]);
  }
  return named;
};

const configured = hooks(readFileSync('.pre-commit-config.yaml', 'utf8'));

// Read as "no hook after it at all", not "no hook with stages: [pre-commit]".
// A hook without a `stages` key runs at every stage, and so does one that
// names pre-commit among several. Every later hook is therefore a candidate,
// and the only reading that covers them all is the positional one. It costs a
// pre-push hook the last place in the file, which costs nothing.
it('no hook comes after bump-version', () => {
  // A hook the parser could not name would hide behind the last one.
  expect(
    configured.filter((hook) => !hook.id).map((hook) => hook.text),
  ).toEqual([]);
  const ids = configured.map((hook) => hook.id);
  expect(ids).toContain('bump-version');
  expect(ids[ids.length - 1]).toBe('bump-version');
});

// fail_fast stops the run at the first failure. Without it on a hook ahead of
// bump-version, a formatter can say no and the bump still runs, which is the
// same raised-for-nothing number as a hook that comes after it.
it('every commit-stage hook ahead of bump-version fails fast', () => {
  const commit = configured.slice(0, -1).filter((hook) => {
    const stages = stagesOf(hook);
    // The short spelling counts as well, so that a hook written that way is
    // not quietly passed over.
    return (
      stages === null ||
      stages.includes('pre-commit') ||
      stages.includes('commit')
    );
  });
  expect(commit.length).toBeGreaterThan(0);
  const lax = commit
    .filter((hook) => !/^\s*(?:-\s+)?fail_fast:\s*true\s*$/m.test(hook.text))
    .map((hook) => hook.id);
  expect(lax).toEqual([]);
});

it('the service package carries the same version as package.json', () => {
  const init = readFileSync(
    'service/src/video_tldr_service/__init__.py',
    'utf8',
  );
  const match = /^__version__ = "([^"]+)"$/m.exec(init);
  expect(match?.[1]).toBe(version('package.json'));
});
