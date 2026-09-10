import { readdirSync, readFileSync } from 'node:fs';
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

// popup.ts and options.ts query the DOM while they load, so vitest cannot
// import them as they are. These read their source instead, the way
// tests/choices.test.ts reads config.py. Where the behaviour is what
// matters, the block at the end of this file stands a page in instead.
describe('the pages', () => {
  const source = (path: string): string => readFileSync(path, 'utf8');

  function part(path: string, pattern: RegExp): string {
    const match = pattern.exec(source(path));
    if (!match) throw new Error(`${String(pattern)} not found in ${path}`);
    return match[1];
  }

  it('fires no request at the worker whose rejection nobody takes', () => {
    // `void ask(…)` drops the rejection ask() throws on an error reply:
    // a cancel or open for a job the service forgot ends as an unhandled
    // rejection. tell() is the one call that may fire and forget, and it
    // catches.
    for (const line of source('src/popup.ts').split('\n')) {
      if (line.includes('void ask(')) expect(line, line).toContain('.catch(');
    }
  });

  it('stops the benchmark timer when a tick throws', () => {
    // Without the try the tick rejects and the timer keeps polling a
    // service that is already gone, until the page closes.
    const poll = part('src/options.ts', /(setInterval\(async[\s\S]*?)\n\}\);/);
    expect(poll).toContain('try {');
    expect(poll).toMatch(/catch \([\s\S]*clearInterval\(timer\)/);
  });

  it('sends the worker no field it does not know', () => {
    // ask() takes a plain object, so a field background.ts never reads is
    // swallowed without a word. Both texts are compared until ask() is
    // typed to `Ask`.
    const known = part('src/background.ts', /\{ type: 'start';([^}]*)\}/);
    const sent = part('src/popup.ts', /ask\(\{\s*type: 'start',([\s\S]*?)\}\)/);
    for (const [, field] of sent.matchAll(/^\s*(\w+)[,:]/gm)) {
      expect(known, field).toContain(field);
    }
  });

  it('exports nothing from service.ts that no other file reads', () => {
    const files = [
      ...readdirSync('src').map((name) => `src/${name}`),
      ...readdirSync('tests').map((name) => `tests/${name}`),
    ].filter((path) => path.endsWith('.ts') && path !== 'src/service.ts');
    const readers = files.map(source).join('\n');
    for (const [, name] of source('src/service.ts').matchAll(
      /^export (?:const|function|class) (\w+)/gm,
    )) {
      expect(readers, name).toMatch(new RegExp(`\\b${name}\\b`));
    }
  });
});

// The save button of the options page, with a stand-in for the page
// around it. It sends one request per key, and what that loop does when
// the service refuses one is behaviour, not a pattern in the source: a
// test that only read the source stayed green while the loop gave up
// after the first 400. Every element the page asks for answers here, and
// the handlers it registers stay reachable, so the test fires the click.
describe('the options page', () => {
  type Node = Record<string, any>;

  function fakeNode(): Node {
    const node: Node = {
      value: '',
      textContent: '',
      className: '',
      placeholder: '',
      title: '',
      hidden: false,
      checked: false,
      dataset: {},
      handlers: {} as Record<string, () => unknown>,
      addEventListener: (event: string, handler: () => unknown) => {
        node.handlers[event] = handler;
      },
      append: () => undefined,
      replaceChildren: () => undefined,
      querySelectorAll: () => [],
      insertRow: () => fakeNode(),
      insertCell: () => fakeNode(),
      focus: () => undefined,
    };
    return node;
  }

  const CONFIG = {
    settings: {},
    choices: {},
    stt_models: {},
    profiles: [],
    default_models: {},
    browser_found: '',
    home: 'home',
    log: 'log',
    version: '0.0.0',
  };
  const LIGHT = { ok: true, detail: 'fine' };

  // `put` answers a PUT /config for the key it is given, or throws the
  // way fetch does when nothing listens on the port.
  async function openPage(
    put: (key: string) => Response,
  ): Promise<{ nodes: Map<string, Node>; sent: string[] }> {
    const nodes = new Map<string, Node>();
    const element = (selector: string): Node => {
      if (!nodes.has(selector)) nodes.set(selector, fakeNode());
      return nodes.get(selector)!;
    };
    const sent: string[] = [];
    const fetchMock = vi.fn((url: string, init: RequestInit) => {
      if (init.method === 'PUT') {
        const keys = Object.keys(
          JSON.parse(String(init.body)) as Record<string, string>,
        );
        expect(keys).toHaveLength(1);
        sent.push(keys[0]);
        return put(keys[0]);
      }
      if (url.endsWith('/config')) return answer(200, CONFIG);
      if (url.endsWith('/stats')) {
        return answer(200, { runs: 0, steps: {}, models: {}, stt: {} });
      }
      if (url.includes('/models')) return answer(200, { models: [] });
      if (url.endsWith('/health')) {
        return answer(200, { service: LIGHT, llm: LIGHT, stt: LIGHT });
      }
      throw new Error(`no answer for ${init.method} ${url}`);
    });
    vi.stubGlobal('document', {
      querySelector: element,
      querySelectorAll: () => [],
      createElement: () => fakeNode(),
      createTextNode: () => fakeNode(),
    });
    vi.stubGlobal('Option', class {});
    vi.stubGlobal('HTMLSelectElement', class {});
    vi.stubGlobal('browser', {
      i18n: { getMessage: (key: string) => key },
      storage: {
        local: {
          get: (defaults: unknown) => Promise.resolve(defaults),
          set: () => Promise.resolve(),
        },
      },
    });
    vi.stubGlobal('fetch', fetchMock);
    vi.resetModules();
    await import('../src/options.js');
    // GET /config, /stats, /models and /health: the page counts as
    // connected once they are in, which the save button checks first.
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(4));
    return { nodes, sent };
  }

  function save(nodes: Map<string, Node>): Promise<void> {
    return (nodes.get('#save')!.handlers.click as () => Promise<void>)();
  }

  it('keeps saving the other keys when the service refuses one', async () => {
    // Without a token the service answers a 400 per barred key, and its
    // text names the key, so the page must not name it again.
    const { nodes, sent } = await openPage((key) =>
      key === 'download_dir'
        ? answer(400, {
            error: `${key} may not be set over HTTP; \`video-tldr config --set ${key}=...\` on the machine that runs the service does it`,
          })
        : answer(200, CONFIG),
    );

    await save(nodes);

    // The fifteen fields of the page and `formats`, one request each.
    expect(sent).toHaveLength(16);
    expect(sent).toContain('download_dir');
    expect(sent).toContain('formats');
    const said = String(nodes.get('#status')!.textContent);
    expect(said).toContain('download_dir may not be set over HTTP');
    expect(said).not.toContain('download_dir: download_dir');
    expect(nodes.get('#status')!.className).toBe('status bad');
  });

  it('asks once and says so when the service is gone', async () => {
    const { nodes, sent } = await openPage(() => {
      throw new TypeError('fetch failed');
    });

    await save(nodes);

    expect(sent).toHaveLength(1);
    expect(nodes.get('#status')!.textContent).toBe(
      'no service at http://127.0.0.1:8765',
    );
  });

  it('asks once and says so when the token is refused', async () => {
    const { nodes, sent } = await openPage(() =>
      answer(401, { error: 'wrong token' }),
    );

    await save(nodes);

    expect(sent).toHaveLength(1);
    expect(nodes.get('#status')!.textContent).toBe('wrong token');
  });

  it('names every refused key, in the order the keys went out', async () => {
    const barred = new Set(['download_dir', 'browser']);
    const { nodes, sent } = await openPage((key) =>
      barred.has(key)
        ? answer(400, { error: `${key} may not be set over HTTP` })
        : answer(200, CONFIG),
    );

    await save(nodes);

    expect(sent).toHaveLength(16);
    expect(nodes.get('#status')!.textContent).toBe(
      'download_dir may not be set over HTTP · browser may not be set over HTTP',
    );
  });

  it('says a reason two keys share only once', async () => {
    // The page does not word the reason, it passes on what the service
    // sent, so two keys can arrive carrying the same sentence.
    const reason = 'config.json is read-only';
    const barred = new Set(['download_dir', 'browser']);
    const { nodes } = await openPage((key) =>
      barred.has(key) ? answer(400, { error: reason }) : answer(200, CONFIG),
    );

    await save(nodes);

    expect(nodes.get('#status')!.textContent).toBe(reason);
  });

  it('wipes a success and leaves a refusal standing', async () => {
    // The refusal arrives while the wipe of the success before it is
    // still due, which is what a blur half a second earlier looks like.
    let refuse = false;
    const { nodes } = await openPage((key) =>
      refuse && key === 'download_dir'
        ? answer(400, { error: 'barred' })
        : answer(200, CONFIG),
    );
    const said = nodes.get('#status')!;
    vi.useFakeTimers();
    try {
      await save(nodes);
      vi.advanceTimersByTime(6000);
      expect(said.textContent).toBe('');

      await save(nodes);
      refuse = true;
      await save(nodes);
      vi.advanceTimersByTime(6000);
      expect(said.textContent).toBe('barred');
    } finally {
      vi.useRealTimers();
    }
  });
});

// The worker. background.ts registers its listeners while it loads and
// reaches the browser only through api.*, so a stand-in for that
// namespace runs a poll from the command line. What the worker tracks
// lives in storage.local, because a Manifest V3 worker ends between two
// events, so the stand-in keeps a store and the tests read it back.
describe('the worker', () => {
  interface Fake {
    store: Record<string, unknown>;
    // One entry per setIcon: true for the coloured icon, false for grey.
    icons: boolean[];
    alarms: string[];
    cleared: string[];
    notified: string[];
    poll: () => Promise<void>;
    blink: () => void;
  }

  // `reply` answers GET /jobs/<id>: a job, or a status to fail with. 0
  // stands for a fetch that never got through, the service being away.
  // `quotes` says what an error answer names, the id by default and a path
  // where an older service would name one. `notifyFails` makes the browser
  // turn the notification away, as one without a notification service does.
  async function loadWorker(
    jobs: string[],
    reply: (id: string) => Job | number,
    store: Record<string, unknown> = {},
    quotes: (id: string) => string = (id) => id,
    notifyFails = false,
  ): Promise<Fake> {
    const state: Record<string, unknown> = { jobs, ...store };
    const icons: boolean[] = [];
    const alarms: string[] = [];
    const cleared: string[] = [];
    const notified: string[] = [];
    const nothing = { addListener: () => undefined };
    vi.stubGlobal('browser', {
      i18n: { getMessage: (key: string) => key },
      runtime: {
        onInstalled: nothing,
        onMessage: nothing,
        getURL: (path: string) => path,
      },
      contextMenus: { create: () => undefined, onClicked: nothing },
      notifications: {
        onClicked: nothing,
        create: (id: string) => {
          if (notifyFails) {
            return Promise.reject(new Error('no notification service'));
          }
          notified.push(id);
          return Promise.resolve(id);
        },
      },
      alarms: {
        onAlarm: nothing,
        create: (name: string) => {
          alarms.push(name);
          return Promise.resolve();
        },
        clear: (name: string) => {
          cleared.push(name);
          return Promise.resolve(true);
        },
      },
      action: {
        setIcon: (details: { path: Record<number, string> }) => {
          icons.push(details.path[16].includes('/active-'));
          return Promise.resolve();
        },
        setBadgeText: () => Promise.resolve(),
        setBadgeBackgroundColor: () => Promise.resolve(),
        setTitle: () => Promise.resolve(),
      },
      storage: {
        local: {
          get: (defaults: Record<string, unknown>) =>
            Promise.resolve(
              Object.fromEntries(
                Object.keys(defaults).map((key) => [
                  key,
                  key in state ? state[key] : defaults[key],
                ]),
              ),
            ),
          set: (values: Record<string, unknown>) => {
            Object.assign(state, values);
            return Promise.resolve();
          },
        },
      },
    });
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string) => {
        if (url.endsWith('/health')) return answer(200, {});
        const id = url.split('/jobs/')[1];
        const result = reply(id);
        if (typeof result !== 'number') return answer(200, result);
        if (result === 0) throw new TypeError('fetch failed');
        // Worded the way the service words it, because the worker reads
        // the text apart: serve.py raises KeyError(<id>) for a job it does
        // not know and KeyError(self.path) for a path it does not know, and
        // `str` on either quotes it.
        return answer(result, { error: `no such thing: '${quotes(id)}'` });
      }),
    );
    vi.resetModules();
    const worker = (await import('../src/background.js')) as {
      poll: () => Promise<void>;
      blink: () => void;
    };
    // checkService asks GET /health while the module loads and paints the
    // icon once; what the tests watch starts after that.
    await vi.waitFor(() => expect(icons.length).toBeGreaterThan(0));
    icons.length = 0;
    return {
      store: state,
      icons,
      alarms,
      cleared,
      notified,
      poll: worker.poll,
      blink: worker.blink,
    };
  }

  const running: Job = {
    id: 'a',
    url: 'u',
    status: 'running',
    step: 'analyze',
  };

  it('keeps every job while the service is away, and polls on', async () => {
    // The service restarting used to throw every running job out of the
    // list at once, which stopped the poll and lost every notification.
    const worker = await loadWorker(['a', 'b'], () => 0);

    await worker.poll();

    expect(worker.store.jobs).toEqual(['a', 'b']);
    expect(worker.cleared).not.toContain('poll-job');
    expect(worker.icons).toEqual([false]);
  });

  it('drops the job the service answers 404 for, and no other', async () => {
    // 404 is the one answer that says the job is gone (serve.py: GET
    // /jobs/<id> is 200 or 404); a 500 says nothing about it.
    const worker = await loadWorker(['gone', 'broken', 'a'], (id) => {
      if (id === 'gone') return 404;
      if (id === 'broken') return 500;
      return { ...running, id };
    });

    await worker.poll();

    expect(worker.store.jobs).toEqual(['broken', 'a']);
    expect(worker.cleared).not.toContain('poll-job');
    // A status, 404 included, came from a service that is up.
    expect(worker.icons).toEqual([true]);
  });

  it('paints the icon back when the service answers again', async () => {
    const worker = await loadWorker(['a'], (id) => ({ ...running, id }), {
      misses: 3,
    });

    await worker.poll();

    // Once per round, not once per job, and coloured again after a miss.
    expect(worker.icons).toEqual([true]);
    expect(worker.store.misses).toBe(0);
    expect(worker.store.jobs).toEqual(['a']);
  });

  it('gives up on jobs the service has not answered for in ages', async () => {
    const worker = await loadWorker(['a'], () => 0, { misses: 1000 });

    await worker.poll();

    expect(worker.store.jobs).toEqual([]);
    expect(worker.cleared).toContain('poll-job');
  });

  it('notifies a finished job and takes it out of the list', async () => {
    const worker = await loadWorker(['a'], (id) => ({
      ...running,
      id,
      status: 'done',
    }));

    await worker.poll();

    expect(worker.notified).toEqual(['done:a']);
    expect(worker.store.jobs).toEqual([]);
    expect(worker.cleared).toContain('poll-job');
  });

  it('keeps a job the service answers 404 about some other path for', async () => {
    // Not every 404 is about the job. An older service without
    // GET /jobs/<id> answers one for the path, and serve.py quotes the
    // path then (`'/jobs/a'`), not the id. Reading that as "the job is
    // gone" would drop every id in the first round, which is the very
    // symptom the 404 handling is there to avoid.
    const worker = await loadWorker(
      ['a', 'b'],
      () => 404,
      {},
      (id) => `/jobs/${id}`,
    );

    await worker.poll();

    expect(worker.store.jobs).toEqual(['a', 'b']);
    // It counts as no answer, so the limit ends it rather than it waiting
    // for ever.
    expect(worker.store.misses).toBe(1);
    expect(worker.cleared).toEqual([]);
  });

  it('finishes the round when the browser turns the notification away', async () => {
    // The icon, the shortened list and the alarm that stops the poll all
    // happen after the loop. An unhandled rejection from notifications
    // .create would skip all three: the finished id would stay in the list
    // and the alarm would wake the worker every half minute for the life of
    // the profile to fail at the same notification again.
    const worker = await loadWorker(
      ['a'],
      (id) => ({ ...running, id, status: 'done' }),
      {},
      undefined,
      true,
    );

    await worker.poll();

    expect(worker.store.jobs).toEqual([]);
    expect(worker.cleared).toEqual(['poll-job']);
    expect(worker.icons.at(-1)).toBe(true);
  });

  it('blinks on a timer, because no alarm repeats twice a second', async () => {
    // 500 ms is far under the floor for a repeating alarm, so the blink
    // must not hang on one: a packed extension would flip the icon every
    // 30 seconds instead of twice a second.
    const worker = await loadWorker([], () => 0);

    vi.useFakeTimers();
    try {
      worker.blink();
      await vi.advanceTimersByTimeAsync(6000);
    } finally {
      vi.useRealTimers();
    }

    expect(worker.alarms).toEqual([]);
    expect(worker.icons).toHaveLength(12);
    expect(worker.icons.slice(0, 3)).toEqual([false, true, false]);
    // Coloured at the end, whatever the flipping left behind.
    expect(worker.icons.at(-1)).toBe(true);
  });

  it('declares nothing in the manifest that lets a page send to it', () => {
    // The onMessage listener does not check the sender, and the comment
    // there says what that rests on: without these two keys nothing but
    // the extension's own pages can send. Either one arriving makes the
    // check necessary.
    const manifest = JSON.parse(
      readFileSync('src/manifest.json', 'utf8'),
    ) as Record<string, unknown>;

    expect(manifest.externally_connectable).toBeUndefined();
    expect(manifest.content_scripts).toBeUndefined();
  });
});
