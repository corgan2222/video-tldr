import { readFileSync } from 'node:fs';
import { expect, it } from 'vitest';
import { DEFAULT_CHOICES, DEFAULT_SETTINGS } from '../src/service.js';

// The options page shows the service's choices and defaults before it
// is connected, from a copy in service.ts. This reads config.py, the
// original, so a backend or a default added there fails here until the
// copy follows.
const source = readFileSync(
  'service/src/corganshelper_service/config.py',
  'utf8',
);

function pythonList(name: string): string[] {
  const match = new RegExp(`^${name} = \\[([^\\]]*)\\]`, 'm').exec(source);
  if (!match) throw new Error(`${name} not found in config.py`);
  return [...match[1].matchAll(/"([^"]+)"/g)].map((m) => m[1]);
}

// The body of `name = {...}`: up to the closing brace at the start of a
// line for a dict written over several lines, or on the same line for a
// one-liner like LANGUAGES.
function pythonDict(name: string): string {
  const start = source.indexOf(`${name} = {`);
  if (start < 0) throw new Error(`${name} not found in config.py`);
  const rest = source.slice(start + name.length + 4);
  const end = rest.search(/\n\}|\}\n/);
  return rest.slice(0, end);
}

function pythonDictKeys(name: string): string[] {
  const body = pythonDict(name);
  // Only the outer keys of a nested dict: those sit at four spaces.
  const keys = body.includes('\n') ? /^    "([^"]+)": /gm : /"([^"]+)": /g;
  return [...body.matchAll(keys)].map((m) => m[1]);
}

function pythonDictValue(name: string, key: string): string {
  const match = new RegExp(`^    "${key}": "([^"]*)"`, 'm').exec(
    pythonDict(name),
  );
  if (!match) throw new Error(`${name}[${key}] not found in config.py`);
  return match[1];
}

it('the choices shown before connecting are the ones config.py has', () => {
  expect(DEFAULT_CHOICES.llm).toEqual(pythonList('LLM_BACKENDS'));
  expect(DEFAULT_CHOICES.formats).toEqual(pythonList('FORMATS'));
  expect(DEFAULT_CHOICES.language).toEqual(pythonDictKeys('LANGUAGES'));
  expect(DEFAULT_CHOICES.stt).toEqual([
    'auto',
    'subtitles',
    ...pythonDictKeys('STT_MODELS'),
  ]);
});

it('the defaults shown before connecting are the ones config.py has', () => {
  for (const [key, value] of Object.entries(DEFAULT_SETTINGS)) {
    expect(pythonDictValue('DEFAULTS', key), key).toBe(value);
  }
});
