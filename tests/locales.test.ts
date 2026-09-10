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
