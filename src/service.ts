// What the popup, the options page and the background share when they
// talk to the local service: the stored connection, one request shape,
// the job model, and the arithmetic behind the badge and the time
// estimate. No browser API in here, so vitest runs it as it is.

export const NAME = 'video-tltr';

export interface Connection {
  serviceUrl: string;
  token: string;
}

export const DEFAULT_CONNECTION: Connection = {
  serviceUrl: 'http://127.0.0.1:8765',
  token: '',
};

// Without a port on purpose: Firefox drops a host permission that carries
// one. The port lives in serviceUrl.
export const HOST_PATTERN = 'http://127.0.0.1/*';

// The service's steps, in order (run.py STEPS; tests/choices.test.ts
// keeps the two lists equal). `note` writes the summary before the
// expensive steps.
export const STEPS = [
  'fetch',
  'transcribe',
  'analyze',
  'note',
  'enrich',
  'frames',
  'render',
];

export const STEP_LABEL: Record<string, string> = {
  fetch: 'Fetch title, description, captions',
  transcribe: 'Transcribe',
  analyze: 'Summarise with the language model',
  note: 'Write the note',
  enrich: 'Read the linked repositories',
  frames: 'Pick and label pictures',
  render: 'Render the outputs',
};

export type Profile = 'fast' | 'thorough';

// What the options page shows before the service has answered: the
// choices and defaults of the service's config.py, mirrored here so the
// page makes sense without a connection. tests/choices.test.ts compares
// them with config.py; the service's own answer replaces them once it
// is connected.
export const DEFAULT_CHOICES: Record<string, string[]> = {
  llm: ['claude', 'anthropic', 'openai', 'lmstudio', 'ollama'],
  stt: [
    'auto',
    'subtitles',
    'whisper',
    'whisper-large',
    'parakeet',
    'canary',
    'openai',
  ],
  formats: ['md', 'obsidian', 'pdf', 'docx'],
  language: ['de', 'en'],
};

export const DEFAULT_SETTINGS: Record<string, string> = {
  llm: 'claude',
  model: '',
  stt: 'auto',
  language: 'de',
  formats: 'md',
  obsidian_folder: 'Videos',
  lmstudio_url: 'http://localhost:1234/v1',
  ollama_url: 'http://localhost:11434/v1',
};

export type JobStatus = 'queued' | 'running' | 'done' | 'error';

export interface Job {
  id: string;
  url: string;
  status: JobStatus;
  profile?: Profile;
  step: string | null;
  step_started?: string | null;
  steps?: Record<string, number>;
  seconds?: number;
  title?: string | null;
  model?: string;
  stt?: string;
  images?: number;
  input?: number;
  output?: number;
  usd?: number;
  error?: { step: string; message: string } | null;
  written?: Record<string, string>;
  queued?: string;
  started?: string;
  finished?: string;
}

export interface SttModel {
  engine: string;
  model: string;
  speed: string;
  wer: string;
  languages: string;
}

export interface Config {
  settings: Record<string, string>;
  choices: Record<string, string[]>;
  stt_models: Record<string, SttModel>;
  profiles: string[];
  home: string;
  log: string;
  version: string;
}

export interface Measure {
  runs: number;
  seconds: number;
  input: number;
  output: number;
  usd: number;
}

// What earlier runs took, from GET /stats: the median seconds per step
// and what each language model and transcriber cost.
export interface Stats {
  runs: number;
  steps: Record<string, number>;
  models: Record<string, Measure>;
  stt: Record<string, Measure>;
}

export class ServiceError extends Error {
  constructor(
    message: string,
    readonly status?: number,
  ) {
    super(message);
  }
}

// The token goes to this host and to no other: a URL pasted into the
// options must not turn the extension into a courier.
export function isLocal(serviceUrl: string): boolean {
  try {
    const url = new URL(serviceUrl);
    return url.protocol === 'http:' && url.hostname === '127.0.0.1';
  } catch {
    return false;
  }
}

// One request to the service. The token travels as a bearer header; the
// service answers JSON on every path, errors included, and a network
// failure means the service is not running.
export async function request<T>(
  connection: Connection,
  method: string,
  path: string,
  body?: unknown,
): Promise<T> {
  const base = connection.serviceUrl.replace(/\/+$/, '');
  if (!isLocal(base)) {
    throw new ServiceError(
      `the service URL must be http://127.0.0.1 with a port, not ${base}`,
    );
  }
  const headers: Record<string, string> = {
    Authorization: `Bearer ${connection.token}`,
  };
  if (body !== undefined) headers['Content-Type'] = 'application/json';
  let response: Response;
  try {
    response = await fetch(`${base}${path}`, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch {
    throw new ServiceError(
      `no service at ${base}; start it with "video-tltr serve"`,
    );
  }
  const data = (await response.json().catch(() => ({}))) as {
    error?: string;
  };
  if (!response.ok) {
    throw new ServiceError(
      data.error ?? `${response.status} ${response.statusText}`,
      response.status,
    );
  }
  return data as T;
}

// The eleven-character id of a YouTube watch, share, shorts or embed
// URL, as fetch.video_id reads it; null for anything else.
export function videoId(url: string): string | null {
  let parsed: URL;
  try {
    parsed = new URL(url);
  } catch {
    return null;
  }
  const host = parsed.hostname.toLowerCase().replace(/^(www|m)\./, '');
  let candidate: string | undefined;
  if (host === 'youtu.be') {
    candidate = parsed.pathname.split('/')[1];
  } else if (host === 'youtube.com' || host === 'music.youtube.com') {
    if (parsed.pathname === '/watch') {
      candidate = parsed.searchParams.get('v') ?? undefined;
    } else {
      const [, kind, id] = parsed.pathname.split('/');
      if (['shorts', 'embed', 'live', 'v'].includes(kind)) candidate = id;
    }
  }
  return candidate && /^[A-Za-z0-9_-]{11}$/.test(candidate) ? candidate : null;
}

export type StepState = 'done' | 'running' | 'pending' | 'failed';

export interface StepView {
  name: string;
  label: string;
  state: StepState;
  // Seconds taken (done), running so far (running) or expected (pending);
  // null when nothing is known yet.
  seconds: number | null;
}

// One line per step for the popup, with the seconds each took, takes or
// is expected to take from earlier runs.
export function stepViews(job: Job, stats: Stats, now: Date): StepView[] {
  const done = job.steps ?? {};
  const current = job.status === 'running' ? job.step : null;
  const failed = job.status === 'error' ? job.error?.step : null;
  return STEPS.map((name) => {
    const label = STEP_LABEL[name] ?? name;
    if (name in done) {
      return { name, label, state: 'done', seconds: done[name] };
    }
    if (name === failed) return { name, label, state: 'failed', seconds: null };
    if (name === current) {
      const since = job.step_started ? Date.parse(job.step_started) : NaN;
      const elapsed = Number.isNaN(since)
        ? null
        : (now.getTime() - since) / 1000;
      return { name, label, state: 'running', seconds: elapsed };
    }
    return {
      name,
      label,
      state: 'pending',
      seconds: stats.steps[name] ?? null,
    };
  });
}

// Seconds until the job is done, from the medians of earlier runs: the
// pending steps in full, the running one less what it has used. Null
// when no earlier run says anything about a step still ahead.
export function remainingSeconds(
  job: Job,
  stats: Stats,
  now: Date,
): number | null {
  if (job.status === 'done' || job.status === 'error') return 0;
  let total = 0;
  let known = false;
  for (const view of stepViews(job, stats, now)) {
    if (view.state === 'done') continue;
    const expected = stats.steps[view.name];
    if (expected === undefined) continue;
    known = true;
    total +=
      view.state === 'running'
        ? Math.max(0, expected - (view.seconds ?? 0))
        : expected;
  }
  return known ? Math.round(total) : null;
}

export function formatSeconds(seconds: number): string {
  if (seconds < 60) return `${Math.round(seconds)} s`;
  const minutes = Math.floor(seconds / 60);
  return `${minutes}:${String(Math.round(seconds % 60)).padStart(2, '0')} min`;
}

export interface Badge {
  text: string;
  color: string;
  title: string;
}

// The badge holds about four characters, so each step gets a short name.
const STEP_BADGE: Record<string, string> = {
  fetch: 'get',
  transcribe: 'stt',
  analyze: 'llm',
  note: 'md',
  enrich: 'git',
  frames: 'img',
  render: 'out',
};

const GREY = '#5f6368';
const BLUE = '#1a73e8';
const GREEN = '#188038';
const RED = '#d93025';

export function badgeFor(job: Job): Badge {
  const what = job.title ?? job.id;
  switch (job.status) {
    case 'queued':
      return { text: '…', color: GREY, title: `${NAME}: queued ${what}` };
    case 'running':
      return {
        text: STEP_BADGE[job.step ?? ''] ?? '…',
        color: BLUE,
        title: `${NAME}: ${job.step ?? 'working on'} ${what}`,
      };
    case 'done':
      return {
        text: '✓',
        color: GREEN,
        title: `${NAME}: done, ${what}. Click the icon to open it.`,
      };
    case 'error':
      return failureBadge(
        `${job.error?.step ?? 'job'} failed: ${job.error?.message ?? 'unknown error'}`,
      );
  }
}

export function failureBadge(message: string): Badge {
  return { text: '!', color: RED, title: `${NAME}: ${message}` };
}
