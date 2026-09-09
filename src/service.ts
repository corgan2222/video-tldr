// What the background and the options page share when they talk to the
// local service: the stored connection, one request shape, and the badge
// for a job state. No browser API in here, so vitest runs it as it is.

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

export type JobStatus = 'queued' | 'running' | 'done' | 'error';

export interface Job {
  id: string;
  url: string;
  status: JobStatus;
  step: string | null;
  title?: string | null;
  error?: { step: string; message: string } | null;
  written?: Record<string, string>;
}

export interface Config {
  settings: Record<string, string>;
  choices: Record<string, string[]>;
  home: string;
  version: string;
}

export class ServiceError extends Error {
  constructor(
    message: string,
    readonly status?: number,
  ) {
    super(message);
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
      `no service at ${base}; start it with "corganshelper serve"`,
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
      return { text: '…', color: GREY, title: `corganshelper: queued ${what}` };
    case 'running':
      return {
        text: STEP_BADGE[job.step ?? ''] ?? '…',
        color: BLUE,
        title: `corganshelper: ${job.step ?? 'working on'} ${what}`,
      };
    case 'done':
      return {
        text: '✓',
        color: GREEN,
        title: `corganshelper: done, ${what}. Click the notification to open it.`,
      };
    case 'error':
      return failureBadge(
        `${job.error?.step ?? 'job'} failed: ${job.error?.message ?? 'unknown error'}`,
      );
  }
}

export function failureBadge(message: string): Badge {
  return { text: '!', color: RED, title: `corganshelper: ${message}` };
}
