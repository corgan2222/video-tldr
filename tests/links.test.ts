import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import {
  DEFAULT_BLOCKLIST,
  extractFromText,
  isBlocked,
  normalize,
  planOpen,
  unwrapRedirect,
} from '../src/links.js';

// The anchors of the description of youtube.com/watch?v=BT4ywlPr6Pk as the
// watch page carries them: every one wrapped in youtube.com/redirect?q=…
// Captured 2026-09-09 from the page's ytInitialData.
const fixture = JSON.parse(
  readFileSync('tests/fixtures/bt4-description.json', 'utf8'),
) as { hrefs: string[]; targets: string[] };

describe('unwrapRedirect', () => {
  it('takes the q parameter out of a youtube redirect', () => {
    expect(
      unwrapRedirect(
        'https://www.youtube.com/redirect?event=video_description&redir_token=x&q=https%3A%2F%2Fgithub.com%2Fa%2Fb&v=BT4ywlPr6Pk',
      ),
    ).toBe('https://github.com/a/b');
  });

  it('takes the q parameter out of a google url redirect', () => {
    expect(
      unwrapRedirect('https://www.google.com/url?q=https://example.org/x&sa=D'),
    ).toBe('https://example.org/x');
  });

  it('leaves a plain link alone', () => {
    expect(unwrapRedirect('https://github.com/a/b')).toBe(
      'https://github.com/a/b',
    );
  });
});

describe('normalize', () => {
  it('drops fragment, tracking parameters and the trailing slash', () => {
    expect(normalize('HTTPS://GitHub.com/a/b/?utm_source=yt&ref=1#top')).toBe(
      'https://github.com/a/b?ref=1',
    );
  });

  it('rejects anything that is not http or https', () => {
    expect(normalize('mailto:x@example.org')).toBeNull();
    expect(normalize('not a url')).toBeNull();
  });
});

describe('isBlocked', () => {
  it('matches the host and its subdomains, not a lookalike', () => {
    expect(
      isBlocked('https://www.youtube.com/watch?v=1', DEFAULT_BLOCKLIST),
    ).toBe(true);
    expect(isBlocked('https://youtu.be/1', DEFAULT_BLOCKLIST)).toBe(true);
    expect(isBlocked('https://notyoutube.com/', DEFAULT_BLOCKLIST)).toBe(false);
  });
});

describe('extractFromText', () => {
  it('finds full urls and skips the ones youtube shortened with an ellipsis', () => {
    const text =
      'See https://github.com/a/b, and https://github.com/c/d/very/lo… too.';
    expect(extractFromText(text)).toEqual(['https://github.com/a/b']);
  });
});

describe('planOpen on the BT4ywlPr6Pk description', () => {
  const expected = fixture.targets
    .map((t) => normalize(t))
    .filter((t): t is string => t !== null && !isBlocked(t, DEFAULT_BLOCKLIST));

  it('opens every non-blocked target exactly once, unwrapped', () => {
    const plan = planOpen(
      { hrefs: fixture.hrefs, text: '' },
      DEFAULT_BLOCKLIST,
      new Set(),
    );
    expect(new Set(plan.open)).toEqual(new Set(expected));
    expect(plan.open.length).toBe(expected.length);
    expect(plan.open.some((u) => u.includes('youtube.com/redirect'))).toBe(
      false,
    );
  });

  it('opens nothing the second time round', () => {
    const first = planOpen(
      { hrefs: fixture.hrefs, text: '' },
      DEFAULT_BLOCKLIST,
      new Set(),
    );
    const seen = new Set(first.open);
    const second = planOpen(
      { hrefs: fixture.hrefs, text: '' },
      DEFAULT_BLOCKLIST,
      seen,
    );
    expect(second.open).toEqual([]);
    expect(second.known).toBe(first.open.length);
  });

  it('has github links to open, which is what the owner selects it for', () => {
    expect(
      expected.filter((u) => u.startsWith('https://github.com/')).length,
    ).toBeGreaterThan(20);
  });
});
