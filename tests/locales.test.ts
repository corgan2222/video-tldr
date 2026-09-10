import { readdirSync, readFileSync } from 'node:fs';
import { expect, it } from 'vitest';

const messages = (locale: string): Record<string, unknown> =>
  JSON.parse(readFileSync(`src/_locales/${locale}/messages.json`, 'utf8'));

const locales = readdirSync('src/_locales');
const reference = 'en';

// A key that exists in one language only shows up in the interface as its
// own name — no error, no fallback the user would notice. The pair is
// edited by hand every time a string is added, so the drift is a matter
// of when, not whether.
it.each(locales.filter((locale) => locale !== reference))(
  'locale %s carries the same keys as ' + reference,
  (locale) => {
    expect(Object.keys(messages(locale)).sort()).toEqual(
      Object.keys(messages(reference)).sort(),
    );
  },
);

it('every message has a non-empty text', () => {
  for (const locale of locales) {
    for (const [key, entry] of Object.entries(messages(locale))) {
      expect(
        (entry as { message?: string }).message,
        `${locale}/${key}`,
      ).toBeTruthy();
    }
  }
});

const sources = (dir: string): string[] =>
  readdirSync(dir, { withFileTypes: true }).flatMap((entry) =>
    entry.isDirectory()
      ? entry.name === '_locales'
        ? []
        : sources(`${dir}/${entry.name}`)
      : /\.(ts|html)$|manifest\.json$/.test(entry.name)
        ? [`${dir}/${entry.name}`]
        : [],
  );

// A key nobody asks for is dead weight that still has to be translated
// twice. Five of them had collected by 2026-09-10 (extensionName,
// openSettings, statsHeading, statsHelp, video), because nothing here
// looked.
//
// The check asks for the name inside quotes rather than for `t('key')`: the
// step and status labels travel through the STEP_KEY table in service.ts as
// plain string values, and a stricter pattern would call all sixteen of
// them dead. The price is a name that also serves as an element id or a
// menu context, which this cannot tell apart from a real use. It errs
// towards keeping, so it never asks for a key that is in use.
it('every key is asked for somewhere in src/', () => {
  const haystack = sources('src')
    .map((file) => readFileSync(file, 'utf8'))
    .join('\n');
  const unused = Object.keys(messages(reference)).filter(
    (key) => !new RegExp(`['"\`]${key}['"\`]`).test(haystack),
  );
  expect(unused).toEqual([]);
});
