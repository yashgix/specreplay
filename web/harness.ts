/** Loads one commit's real MCP tools once and runs single calls against a fresh fake API. */
import { BASE_URL, createFake } from './fakeapi.ts';
import type { FakeApi, RequestRecord } from './fakeapi.ts';
import type { Spec } from './openapi.ts';

export type Outcome = { outcome: string; detail: string };

export type CallResult = {
  rejected: string | null;
  outcomes: Outcome[];
  requests: RequestRecord[];
  overLimit: boolean;
};

export type ToolInfo = { name: string; shape: Record<string, unknown> };

export type Session = {
  tools: ToolInfo[];
  call(name: string, args: Record<string, unknown>, overrides?: Map<string, unknown>): Promise<CallResult>;
};

type Issue = { path: (string | number)[] };
type Parsed = { success: boolean; data?: unknown; error?: { issues: Issue[] } };
type Schema = { safeParse(value: unknown): Parsed };
type Zod = { object(shape: Record<string, unknown>): Schema };
type Handler = (args: unknown) => unknown;
type Register = (server: Record<string, unknown>, api: unknown) => unknown;
type ApiClass = new (baseUrl: string, apiKey: string) => unknown;
type Registered = { shape: Record<string, unknown>; handler: Handler };

const DEFECTS = ['undefined', 'NaN', '[object Object]'];

/** The repo root, from the CLI path Node puts in argv[1]. */
const ROOT = (() => {
  const entry = process.argv[1] ?? '';
  const dir = entry.slice(0, entry.lastIndexOf('/') + 1);
  return new URL('../', `file://${dir.startsWith('/') ? '' : '/'}${dir}`);
})();

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function pathsOf(error: { issues: Issue[] } | undefined): string {
  const paths = (error?.issues ?? []).map((issue) =>
    issue.path.length === 0 ? '$' : issue.path.map(String).join('.'),
  );
  return [...new Set(paths)].sort().join(';');
}

function textOf(result: unknown): string {
  if (!isRecord(result) || !Array.isArray(result.content)) return '';
  const parts: string[] = [];
  for (const item of result.content) {
    if (isRecord(item) && typeof item.text === 'string') parts.push(item.text);
  }
  return parts.join('\n');
}

function firstLineText(text: string): string {
  const line = text.split('\n')[0] ?? '';
  return line.slice(0, 120);
}

function firstLine(value: unknown): string {
  return firstLineText(value instanceof Error ? value.message : String(value));
}

function classify(name: string, result: unknown, fake: FakeApi, schemas: Record<string, Schema>): CallResult {
  const { requests, overLimit } = fake;
  const text = textOf(result);
  const failed = isRecord(result) && result.isError === true;
  if (failed && requests.length === 0) {
    return { rejected: `refused: ${firstLineText(text)}`, outcomes: [], requests, overLimit };
  }
  if (overLimit) return { rejected: null, outcomes: [{ outcome: 'request_limit', detail: '' }], requests, overLimit };
  if (failed) return { rejected: null, outcomes: [{ outcome: 'error_result', detail: firstLineText(text) }], requests, overLimit };
  const outcomes: Outcome[] = [];
  const schema = schemas[name] as Schema | undefined;
  if (schema !== undefined) {
    const structured = isRecord(result) ? result.structuredContent : undefined;
    if (structured === undefined) {
      outcomes.push({ outcome: 'missing_structured', detail: '' });
    } else {
      const parsed = schema.safeParse(structured);
      if (!parsed.success) outcomes.push({ outcome: 'output_invalid', detail: pathsOf(parsed.error) });
    }
  }
  const defects = DEFECTS.filter((token) => text.includes(token)).sort();
  if (defects.length > 0) outcomes.push({ outcome: 'text_defect', detail: defects.join(';') });
  return { rejected: null, outcomes, requests, overLimit };
}

export async function loadCommit(dir: string, spec: Spec): Promise<Session> {
  const source = new URL(dir.endsWith('/') ? dir : `${dir}/`, ROOT);
  const load = (name: string): Promise<Record<string, unknown>> => import(new URL(name, source).href);
  const [toolsModule, apiModule, schemasModule] = await Promise.all([
    load('src/tools.ts'),
    load('src/api.ts'),
    load('src/output-schemas.ts'),
  ]);
  const zodSpecifier: string = 'zod';
  const zod = (await import(zodSpecifier)) as Record<string, unknown>;

  const register = toolsModule.registerTools as Register | undefined;
  const Api = apiModule.AgentPhoneAPI as ApiClass | undefined;
  const schemas = (schemasModule.OUTPUT_SCHEMAS ?? {}) as Record<string, Schema>;
  const z = (zod.z ?? zod.default) as Zod | undefined;
  if (typeof register !== 'function') throw new Error('src/tools.ts has no registerTools export');
  if (typeof Api !== 'function') throw new Error('src/api.ts has no AgentPhoneAPI export');
  if (z === undefined || typeof z.object !== 'function') throw new Error('the zod entry has no z export');

  const open = (overrides: Map<string, unknown>): { fake: FakeApi; tools: Map<string, Registered> } => {
    const fake = createFake(spec, overrides);
    (globalThis as unknown as { fetch: unknown }).fetch = fake.fetch;
    const api = new Api(BASE_URL, 'test-key');
    const tools = new Map<string, Registered>();
    const server = {
      tool: (...args: unknown[]): undefined => {
        const name = String(args[0]);
        tools.set(name, {
          shape: (args[2] ?? {}) as Record<string, unknown>,
          handler: args[args.length - 1] as Handler,
        });
        return undefined;
      },
    };
    register(server, api);
    return { fake, tools };
  };

  const first = open(new Map());
  const tools: ToolInfo[] = [...first.tools.keys()]
    .sort()
    .map((name) => ({ name, shape: first.tools.get(name)?.shape ?? {} }));

  const call = async (
    name: string,
    args: Record<string, unknown>,
    overrides = new Map<string, unknown>(),
  ): Promise<CallResult> => {
    const { fake, tools: registered } = open(overrides);
    const tool = registered.get(name);
    if (tool === undefined) throw new Error(`tool not registered: ${name}`);
    const parsed = z.object(tool.shape).safeParse(args);
    if (!parsed.success) {
      return { rejected: `input: ${pathsOf(parsed.error)}`, outcomes: [], requests: fake.requests, overLimit: fake.overLimit };
    }
    let result: unknown;
    try {
      result = await tool.handler(parsed.data);
    } catch (error) {
      const overLimit = fake.overLimit;
      return {
        rejected: null,
        outcomes: [{ outcome: overLimit ? 'request_limit' : 'crash', detail: overLimit ? '' : firstLine(error) }],
        requests: fake.requests,
        overLimit,
      };
    }
    return classify(name, result, fake, schemas);
  };

  return { tools, call };
}
