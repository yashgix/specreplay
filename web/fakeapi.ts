/** An in-process stand-in for the AgentPhone API, answering requests from the pinned spec. */
import { example, isConstrained, matchOperation, successResponse } from './openapi.ts';
import type { Spec } from './openapi.ts';

export const BASE_URL = 'https://api.agentphone.test';

/** Requests one call may make before the fake fails it. */
const LIMIT = 10;

const STATUS_TEXT: Record<number, string> = {
  200: 'OK',
  201: 'Created',
  204: 'No Content',
  404: 'Not Found',
};

export type RequestRecord = {
  method: string;
  path: string;
  query: [string, string][];
  body: unknown;
  operation: string | null;
};

export type FakeInit = { method?: string; body?: string };

export type FakeResponse = {
  ok: boolean;
  status: number;
  statusText: string;
  headers: { get(name: string): string | null };
  text(): Promise<string>;
  json(): Promise<unknown>;
};

export type FakeApi = {
  fetch(input: string | URL, init?: FakeInit): Promise<FakeResponse>;
  requests: RequestRecord[];
  overrides: Map<string, unknown>;
  overLimit: boolean;
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

/** The operation object behind a `"METHOD /template"` name. */
export function findOperation(spec: Spec, name: string): Record<string, unknown> | null {
  const space = name.indexOf(' ');
  if (space < 0) return null;
  const method = name.slice(0, space).toLowerCase();
  const template = name.slice(space + 1);
  const paths = isRecord(spec.paths) ? spec.paths : {};
  const item = paths[template];
  if (!isRecord(item)) return null;
  const operation = item[method];
  return isRecord(operation) ? operation : null;
}

function parseBody(raw: string | undefined): unknown {
  if (raw === undefined || raw.length === 0) return undefined;
  try {
    return JSON.parse(raw) as unknown;
  } catch {
    return undefined;
  }
}

function respond(status: number, body: string, json: boolean): FakeResponse {
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: STATUS_TEXT[status] ?? '',
    headers: {
      get: (name: string) => (json && name.toLowerCase() === 'content-type' ? 'application/json' : null),
    },
    text: async () => body,
    json: async () => JSON.parse(body) as unknown,
  };
}

function served(spec: Spec, schema: Record<string, unknown>): unknown {
  return isConstrained(spec, schema) ? example(spec, schema) : {};
}

/** A fresh fake for one tool call: it answers from the spec and never touches the network. */
export function createFake(spec: Spec, overrides: Map<string, unknown> = new Map()): FakeApi {
  const requests: RequestRecord[] = [];
  const api: FakeApi = {
    requests,
    overrides,
    overLimit: false,
    fetch: async (input, init) => {
      if (requests.length >= LIMIT) {
        api.overLimit = true;
        throw new Error(`request limit (${LIMIT}) exceeded`);
      }
      const url = new URL(String(input));
      const method = (init?.method ?? 'GET').toUpperCase();
      const operation = matchOperation(spec, method, url.pathname);
      requests.push({
        method,
        path: url.pathname,
        query: [...url.searchParams],
        body: parseBody(init?.body),
        operation,
      });
      const found = operation === null ? null : findOperation(spec, operation);
      const success = found === null ? null : successResponse(spec, found);
      if (operation === null || success === null) return respond(404, '{"detail":"Not Found"}', true);
      if (success.schema === null) return respond(success.status, '', false);
      const value = overrides.has(operation) ? overrides.get(operation) : served(spec, success.schema);
      return respond(success.status, JSON.stringify(value ?? null), true);
    },
  };
  return api;
}
