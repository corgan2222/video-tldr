import { readdirSync, readFileSync } from 'node:fs';
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

// Windows holds video-tldr.exe open while the process behind it runs, so the
// stop cannot move behind `uv tool install`, and an install that fails leaves
// the machine without a running service and an installation of unknown state.
// The error path has to say that much and no more: a broken-off
// `uv tool install --force` leaves whatever it leaves, so the warning must not
// send the user to `video-tldr serve` as if the old version were still whole.
// No test can half-fail a real install, so what is checked is the shape of the
// script: the order, and a handler that warns and rethrows.
it('a failed install says the installation is of unknown state', () => {
  const install = script.indexOf('& uv tool install');
  const stop = script.indexOf('Stop-RunningService $binDir');
  expect(stop).toBeGreaterThan(-1);
  expect(stop).toBeLessThan(install);
  const rest = script.slice(install);
  const handler = rest.slice(
    rest.indexOf('catch {'),
    rest.indexOf('finally {'),
  );
  expect(handler).toContain('Write-Warning');
  expect(handler).not.toContain('video-tldr serve');
  expect(handler).toContain('throw');
});

const stopFunction = (): string => {
  const fn = script.slice(script.indexOf('function Stop-RunningService'));
  return fn.slice(0, fn.indexOf('function Add-ToUserPath'));
};

// Every line `video-tldr stop` can print, as the installer sees it: the
// returns of stop() in serve.py with their placeholders filled. A return from
// an except branch is one of the answers where the service did not go down,
// which Python's indentation is enough to tell: a line at or left of an
// `except` closes it.
const stopAnswers = (): { text: string; fromExcept: boolean }[] => {
  const serve = readFileSync('service/src/video_tldr_service/serve.py', 'utf8');
  const body = serve.slice(serve.indexOf('\ndef stop(')).split('\ndef ')[1];
  const answers: { text: string; fromExcept: boolean }[] = [];
  let except: number | null = null;
  for (const line of body.split('\n')) {
    const indent = line.search(/\S/);
    if (indent < 0) continue;
    const opens = /^\s*except\b/.test(line);
    if (except !== null && indent <= except && !opens) except = null;
    if (opens) except = indent;
    const returned = /^\s*return f?"(.+)"\s*$/.exec(line);
    if (!returned) continue;
    answers.push({
      text: returned[1].replace(/\{port\}/g, '8765').replace(/\{[^}]*\}/g, 'x'),
      fromExcept: except !== null,
    });
  }
  return answers;
};

// `video-tldr stop` exits 0 whatever it found, so the warning in the catch
// cannot be hung on the exit code, and it cannot be hung on the exe being
// there either: an installed shim with nothing behind it is the ordinary case.
// The cases differ in the line stop prints, so that is what the flag reads.
// Hanging the test on a phrase of its own would let serve.py reword the line
// and leave the flag quiet, so the answers are read from serve.py: exactly one
// of them may match, and it may not be one of the answers that leave the
// service up.
it('the installer tells a stopped service from the rest of what stop says', () => {
  const body = stopFunction();
  const said = /\$said -match '([^']+)'/.exec(body);
  expect(said).not.toBeNull();
  const answers = stopAnswers();
  // One answer cannot be told from another.
  expect(answers.length).toBeGreaterThan(1);
  const matching = answers.filter((answer) =>
    new RegExp(said![1]).test(answer.text),
  );
  expect(matching.map((answer) => answer.text)).toHaveLength(1);
  expect(matching[0].fromExcept).toBe(false);
  expect(body).toContain('$script:askedToStop = $true');
  // So the flag can only rise after the call, never on the exe alone.
  expect(body.indexOf('$script:askedToStop')).toBeGreaterThan(
    body.indexOf('$exe stop'),
  );
});

// Measured on Windows PowerShell 5.1: a native call whose stderr goes into the
// pipeline throws NativeCommandError while $ErrorActionPreference is 'Stop',
// which is what the head of this script sets. The stop is the call that must
// not throw. A throw there ends the run with the service down and the flag
// above still $false, so the warning naming the way back is never printed.
it('the stop runs where a line on stderr cannot end the script', () => {
  const body = stopFunction();
  const relaxed = body.indexOf("$ErrorActionPreference = 'Continue'");
  expect(relaxed).toBeGreaterThan(-1);
  expect(relaxed).toBeLessThan(body.indexOf('$exe stop'));
});

// Every action is pinned to a commit, never to a tag: a tag moves, and the
// code it moves to runs here with whatever the workflow's token may do. The
// directory is read rather than a list of names, so a workflow added later
// cannot slip past this.
it('every workflow pins its actions to a commit SHA', () => {
  const dir = '.github/workflows';
  const floating: string[] = [];
  let read = 0;
  let mentions = 0;
  for (const name of readdirSync(dir)) {
    if (!/\.ya?ml$/.test(name)) continue;
    for (const line of readFileSync(`${dir}/${name}`, 'utf8').split('\n')) {
      if (line.includes('uses:')) mentions++;
      const used = /^\s*(?:-\s+)?uses:\s*(\S+)/.exec(line);
      // A path into this repository carries no SHA and needs none.
      if (!used || used[1].startsWith('./')) continue;
      read++;
      if (!/@[0-9a-f]{40}$/.test(used[1])) floating.push(`${name}: ${used[1]}`);
    }
  }
  expect(floating).toEqual([]);
  // An empty directory and a pattern that stopped matching both leave the
  // check above green with nothing read, so the count is checked as well.
  expect(read).toBe(mentions);
  expect(read).toBeGreaterThan(0);
});

// The asset name comes from the release answer and decides where the download
// lands; a separator in it would write outside the staging directory. The
// guard only helps where it stands, in front of the Join-Path.
it('the installer takes only a plain file name from the release answer', () => {
  const guard = script.indexOf('[IO.Path]::GetFileName($asset.name)');
  const join = script.indexOf('Join-Path $directory $asset.name');
  expect(guard).toBeGreaterThan(-1);
  expect(guard).toBeLessThan(join);
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
