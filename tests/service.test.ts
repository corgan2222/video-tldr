import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  badgeFor,
  failureBadge,
  formatSeconds,
  iconSet,
  isLocal,
  NoServiceError,
  progress,
  remainingSeconds,
  request,
  ServiceError,
  stepViews,
  videoId,
  type Job,
  type Stats,
} from '../src/service.js';

const connection = { serviceUrl: 'http://127.0.0.1:8765/', token: 'secret' };

function answer(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('request', () => {
  it('sends the token, the JSON body and strips the trailing slash', async () => {
    const fetchMock = vi.fn().mockResolvedValue(answer(202, { id: 'x' }));
    vi.stubGlobal('fetch', fetchMock);

    const job = await request<Job>(connection, 'POST', '/jobs', {
      url: 'https://youtu.be/x',
    });

    expect(job.id).toBe('x');
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe('http://127.0.0.1:8765/jobs');
    expect(init.method).toBe('POST');
    expect(init.headers).toEqual({
      Authorization: 'Bearer secret',
      'Content-Type': 'application/json',
    });
    expect(init.body).toBe('{"url":"https://youtu.be/x"}');
  });

  it('sends no content type without a body, no token header without a token', async () => {
    const fetchMock = vi.fn().mockResolvedValue(answer(200, {}));
    vi.stubGlobal('fetch', fetchMock);

    await request(connection, 'GET', '/jobs/x');
    await request({ ...connection, token: '' }, 'GET', '/jobs/x');

    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(init.body).toBeUndefined();
    expect(init.headers).toEqual({ Authorization: 'Bearer secret' });
    const [, open] = fetchMock.mock.calls[1] as [string, RequestInit];
    expect(open.headers).toEqual({});
  });

  it("throws the service's own reason on an error status", async () => {
    vi.stubGlobal(
      'fetch',
      vi
        .fn()
        .mockResolvedValue(answer(400, { error: 'not a YouTube video URL' })),
    );

    await expect(request(connection, 'POST', '/jobs', {})).rejects.toThrow(
      new ServiceError('not a YouTube video URL', 400),
    );
  });

  it('tells a dead service apart from a refusal, so the pages can help', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('refused')));

    // NoServiceError: the pages then show the command that starts it.
    await expect(request(connection, 'GET', '/config')).rejects.toThrow(
      NoServiceError,
    );
    await expect(request(connection, 'GET', '/config')).rejects.toThrow(
      'no service at http://127.0.0.1:8765',
    );
  });
});

describe('isLocal', () => {
  it('accepts 127.0.0.1 over http with any port and nothing else', async () => {
    expect(isLocal('http://127.0.0.1:8765')).toBe(true);
    expect(isLocal('http://127.0.0.1')).toBe(true);
    expect(isLocal('https://127.0.0.1:8765')).toBe(false);
    expect(isLocal('http://localhost:8765')).toBe(false);
    expect(isLocal('http://attacker.example/127.0.0.1')).toBe(false);
    expect(isLocal('not a url')).toBe(false);

    const fetchMock = vi.fn();
    vi.stubGlobal('fetch', fetchMock);
    await expect(
      request(
        { ...connection, serviceUrl: 'https://evil.example' },
        'GET',
        '/config',
      ),
    ).rejects.toThrow('the service URL must be http://127.0.0.1');
    expect(fetchMock).not.toHaveBeenCalled();
  });
});

describe('videoId', () => {
  it('reads the id the way the service does', () => {
    expect(videoId('https://www.youtube.com/watch?v=Zvc5QkrWgAU&t=3')).toBe(
      'Zvc5QkrWgAU',
    );
    expect(videoId('https://youtu.be/Zvc5QkrWgAU')).toBe('Zvc5QkrWgAU');
    expect(videoId('https://m.youtube.com/shorts/Zvc5QkrWgAU')).toBe(
      'Zvc5QkrWgAU',
    );
    expect(videoId('https://www.youtube.com/')).toBeNull();
    expect(videoId('https://www.youtube.com/watch?v=short')).toBeNull();
    expect(videoId('https://example.org/watch?v=Zvc5QkrWgAU')).toBeNull();
    expect(videoId('about:blank')).toBeNull();
  });
});

describe('time estimate', () => {
  const stats: Stats = {
    runs: 3,
    steps: { fetch: 9, analyze: 75, enrich: 8, frames: 240, render: 4 },
    models: {},
    stt: {},
  };
  const now = new Date('2026-09-10T12:00:40+02:00');
  const running: Job = {
    id: 'x',
    url: 'u',
    status: 'running',
    step: 'analyze',
    step_started: '2026-09-10T12:00:10+02:00',
    steps: { fetch: 9.2, transcribe: 0.0 },
  };

  it('lists every step with what it took, takes or is expected to take', () => {
    const views = stepViews(running, stats, now);

    expect(views.map((v) => `${v.name}:${v.state}`)).toEqual([
      'fetch:done',
      'transcribe:done',
      'analyze:running',
      'note:pending',
      'enrich:pending',
      'frames:pending',
      'render:pending',
    ]);
    expect(views[0].seconds).toBe(9.2);
    expect(views[2].seconds).toBe(30);
    expect(views[3].seconds).toBeNull();
    expect(views[5].seconds).toBe(240);
  });

  it('adds the pending medians and what is left of the running step', () => {
    // analyze: 75 expected, 30 used; then enrich 8, frames 240, render 4.
    expect(remainingSeconds(running, stats, now)).toBe(45 + 8 + 240 + 4);
    expect(
      remainingSeconds(
        { ...running, status: 'queued', step: null, steps: {} },
        stats,
        now,
      ),
    ).toBe(9 + 75 + 8 + 240 + 4);
    expect(remainingSeconds({ ...running, status: 'done' }, stats, now)).toBe(
      0,
    );
    expect(remainingSeconds(running, { ...stats, steps: {} }, now)).toBeNull();
  });

  it('fills the bar with what is behind it, and the whole bar when done', () => {
    // 9.2 s spent, 30 s in the running step, 297 s expected after it.
    expect(progress(running, stats, now)).toBeCloseTo(39.2 / 336.2, 3);
    expect(progress({ ...running, status: 'done' }, stats, now)).toBe(1);
    expect(progress(running, { ...stats, steps: {} }, now)).toBe(0);
  });

  it('marks the failed step and formats seconds as minutes', () => {
    const failed: Job = {
      ...running,
      status: 'error',
      error: { step: 'analyze', message: 'boom' },
    };
    expect(stepViews(failed, stats, now)[2].state).toBe('failed');
    expect(formatSeconds(42)).toBe('42 s');
    expect(formatSeconds(297)).toBe('4:57 min');
  });
});

describe('iconSet', () => {
  it('is grey while the service is away and coloured while it answers', () => {
    expect(iconSet(false)[16]).toBe('icons/inactive-16.png');
    expect(iconSet(true)[128]).toBe('icons/active-128.png');
  });
});

describe('badgeFor', () => {
  const job: Job = { id: 'x', url: 'u', status: 'queued', step: null };

  it('shows the step while running and the outcome after', () => {
    expect(badgeFor(job).text).toBe('…');
    expect(
      badgeFor({ ...job, status: 'running', step: 'frames' }),
    ).toMatchObject({ text: 'img', title: 'video-tldr: frames x' });
    expect(badgeFor({ ...job, status: 'running', step: 'odd' }).text).toBe('…');
    expect(
      badgeFor({ ...job, status: 'done', title: 'A video' }).title,
    ).toContain('done, A video');
  });

  it('names the failed step in red', () => {
    const badge = badgeFor({
      ...job,
      status: 'error',
      error: { step: 'frames', message: 'ffmpeg failed' },
    });
    expect(badge).toEqual(failureBadge('frames failed: ffmpeg failed'));
    expect(badge.text).toBe('!');
    expect(badge.title).toBe('video-tldr: frames failed: ffmpeg failed');
  });
});
