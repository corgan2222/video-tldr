import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  badgeFor,
  failureBadge,
  request,
  ServiceError,
  type Job,
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

  it('sends no content type without a body', async () => {
    const fetchMock = vi.fn().mockResolvedValue(answer(200, {}));
    vi.stubGlobal('fetch', fetchMock);

    await request(connection, 'GET', '/jobs/x');

    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(init.body).toBeUndefined();
    expect(init.headers).toEqual({ Authorization: 'Bearer secret' });
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

  it('says how to start the service when nothing answers', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('refused')));

    await expect(request(connection, 'GET', '/config')).rejects.toThrow(
      'no service at http://127.0.0.1:8765; start it with "corganshelper serve"',
    );
  });
});

describe('badgeFor', () => {
  const job: Job = { id: 'x', url: 'u', status: 'queued', step: null };

  it('shows the step while running and the outcome after', () => {
    expect(badgeFor(job).text).toBe('…');
    expect(
      badgeFor({ ...job, status: 'running', step: 'frames' }),
    ).toMatchObject({ text: 'img', title: 'corganshelper: frames x' });
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
    expect(badge.title).toBe('corganshelper: frames failed: ffmpeg failed');
  });
});
