// What the popup, the options page and the background share when they
// talk to the local service: the stored connection, one request shape,
// the job model, and the arithmetic behind the badge and the time
// estimate. No browser API in here, so vitest runs it as it is; the
// texts live in _locales, this file only names their keys.

export const NAME = 'video-tldr';

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

// The message key each step is shown under; the pages translate it.
export const STEP_KEY: Record<string, string> = {
  fetch: 'stepFetch',
  transcribe: 'stepTranscribe',
  analyze: 'stepAnalyze',
  note: 'stepNote',
  enrich: 'stepEnrich',
  frames: 'stepFrames',
  render: 'stepRender',
};

export type Profile = 'fast' | 'thorough';

// The switches the popup offers per run; the service takes them as
// `options` on POST /jobs and falls back to the stored settings.
export interface RunOptions {
  timestamps?: 'on' | 'off';
  condensed?: 'on' | 'off';
  cleanup?: 'on' | 'off';
  style?: string;
}

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
  style: ['normal', 'caveman', 'noslop', 'engineer', 'human', 'all'],
  cleanup: ['on', 'off'],
  timestamps: ['on', 'off'],
  condensed: ['on', 'off'],
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
  download_dir: '',
  pdf_template: '',
  cleanup: 'off',
  timestamps: 'on',
  condensed: 'off',
  style: 'normal',
};

export type JobStatus = 'queued' | 'running' | 'done' | 'error' | 'cancelled';

export interface Job {
  id: string;
  url: string;
  status: JobStatus;
  profile?: Profile;
  options?: RunOptions;
  position?: number;
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
  tokens_per_second?: number;
  error?: { step: string; message: string } | null;
  // Every failure of the run: a step that only adds to the note lets the
  // rest go on, so there can be more than one.
  errors?: { step: string; message: string }[];
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
  default_models: Record<string, string>;
  browser_found: string;
  download_found?: string;
  home: string;
  log: string;
  version: string;
}

export interface Light {
  ok: boolean;
  detail: string;
}

// The lights from GET /health: the service, the language model, the
// transcriber, and what the model can do (images, context).
export interface Health {
  service: Light;
  llm: Light;
  stt: Light;
  capabilities?: Light;
}

export interface Measure {
  runs: number;
  seconds: number;
  input: number;
  output: number;
  usd: number;
  tokens_per_second?: number;
}

// What earlier runs took, from GET /stats: the median seconds per step
// and what each language model and transcriber cost.
export interface Stats {
  runs: number;
  steps: Record<string, number>;
  models: Record<string, Measure>;
  stt: Record<string, Measure>;
}

export interface BenchRow {
  model: string;
  run: number;
  seconds: number;
  input: number;
  output: number;
  tokens_per_second?: number;
  sections?: number;
  key_points?: number;
  links?: number;
  error?: string;
}

// What each backend is: the message key its explanation lives under, so
// the text is translated like every other one. The recommended model
// comes from the service (config.default_models).
export const BACKEND_HELP: Record<string, string> = {
  claude: 'helpBackendClaude',
  anthropic: 'helpBackendAnthropic',
  openai: 'helpBackendOpenai',
  lmstudio: 'helpBackendLmstudio',
  ollama: 'helpBackendOllama',
};

// Which extra fields a backend needs; the options page shows only those.
export const BACKEND_FIELDS: Record<string, string[]> = {
  claude: [],
  anthropic: ['anthropic_api_key'],
  openai: ['openai_api_key', 'openai_base_url'],
  lmstudio: ['lmstudio_url'],
  ollama: ['ollama_url'],
};

export class ServiceError extends Error {
  constructor(
    message: string,
    readonly status?: number,
  ) {
    super(message);
  }
}

// A network failure means the service is not running; the pages show
// the command to start it, so they need to tell that apart.
export class NoServiceError extends ServiceError {}

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
// service answers JSON on every path, errors included.
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
  // The token is optional: a service without one ignores the header, a
  // service with one answers 401 without it.
  const headers: Record<string, string> = {};
  if (connection.token) headers.Authorization = `Bearer ${connection.token}`;
  if (body !== undefined) headers['Content-Type'] = 'application/json';
  let response: Response;
  try {
    response = await fetch(`${base}${path}`, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch {
    throw new NoServiceError(`no service at ${base}`);
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
  labelKey: string;
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
  const failed =
    job.status === 'error' || job.status === 'cancelled'
      ? job.error?.step
      : null;
  return STEPS.map((name) => {
    const labelKey = STEP_KEY[name] ?? name;
    if (name in done) {
      return { name, labelKey, state: 'done', seconds: done[name] };
    }
    if (name === failed) {
      return { name, labelKey, state: 'failed', seconds: null };
    }
    if (name === current) {
      const since = job.step_started ? Date.parse(job.step_started) : NaN;
      const elapsed = Number.isNaN(since)
        ? null
        : (now.getTime() - since) / 1000;
      return { name, labelKey, state: 'running', seconds: elapsed };
    }
    return {
      name,
      labelKey,
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
  if (job.status !== 'queued' && job.status !== 'running') return 0;
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

// How far the job has come, 0 to 1, for the bar: the seconds already
// spent against those plus the ones still expected.
export function progress(job: Job, stats: Stats, now: Date): number {
  if (job.status === 'done') return 1;
  const left = remainingSeconds(job, stats, now);
  if (left === null) return 0;
  const spent = Object.values(job.steps ?? {}).reduce((a, b) => a + b, 0);
  const running = stepViews(job, stats, now).find((v) => v.state === 'running');
  const total = spent + (running?.seconds ?? 0) + left;
  return total > 0 ? Math.min(1, (spent + (running?.seconds ?? 0)) / total) : 0;
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
    case 'cancelled':
      return { text: '×', color: GREY, title: `${NAME}: cancelled ${what}` };
    case 'error':
      return failureBadge(
        `${job.error?.step ?? 'job'} failed: ${job.error?.message ?? 'unknown error'}`,
      );
  }
}

export function failureBadge(message: string): Badge {
  return { text: '!', color: RED, title: `${NAME}: ${message}` };
}

// The toolbar icon: the coloured one while the service answers, the
// grey one while it does not.
export function iconSet(connected: boolean): Record<number, string> {
  const prefix = connected ? 'active' : 'inactive';
  return {
    16: `icons/${prefix}-16.png`,
    32: `icons/${prefix}-32.png`,
    48: `icons/${prefix}-48.png`,
    128: `icons/${prefix}-128.png`,
  };
}
