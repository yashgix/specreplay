/** Scans one source folder against the pinned spec and prints the JSON report. */
import { readFileSync } from 'node:fs';
import {
  apply,
  constraints,
  deref,
  effective,
  example,
  isConstrained,
  isDocumented,
  mutations,
  successResponse,
  validate,
} from './openapi.ts';
import type { Constraints, Spec } from './openapi.ts';
import { findOperation } from './fakeapi.ts';
import type { RequestRecord } from './fakeapi.ts';
import { loadCommit } from './harness.ts';
import type { CallResult, Session } from './harness.ts';

type Finding = {
  tool: string;
  variant: string;
  operation: string;
  mutation: string;
  outcome: string;
  detail: string;
  documented: boolean;
};

type Rejected = { tool: string; variant: string; detail: string };
type Fixture = { variant: string; args: Record<string, unknown> };
type Inputs = { tools: Record<string, Fixture[]> };
type Probe = { arg: string; keyword: string; operation: string; field: string; value: string | number };
type StepRun = { findings: Finding[]; runs: number; requests: number };
type VariantRun = { findings: Finding[]; rejected: Rejected | null; runs: number; requests: number };

const KEYWORDS = ['enum', 'maximum', 'minimum', 'maxLength'] as const;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function finding(
  tool: string,
  variant: string,
  operation: string,
  mutation: string,
  outcome: string,
  detail: string,
  documented: boolean,
): Finding {
  return { tool, variant, operation, mutation, outcome, detail, documented };
}

function readJson(path: string): unknown {
  return JSON.parse(readFileSync(path, 'utf8')) as unknown;
}

function basename(path: string): string {
  const clean = path.replace(/\/+$/, '');
  return clean.slice(clean.lastIndexOf('/') + 1);
}

function pathItem(spec: Spec, operation: string): Record<string, unknown> | null {
  const space = operation.indexOf(' ');
  if (space < 0) return null;
  const paths = isRecord(spec.paths) ? spec.paths : {};
  const item = paths[operation.slice(space + 1)];
  return isRecord(item) ? item : null;
}

function parameterLists(spec: Spec, operation: string): unknown[] {
  const op = findOperation(spec, operation);
  const item = pathItem(spec, operation);
  const lists: unknown[] = [];
  if (op !== null && Array.isArray(op.parameters)) lists.push(op.parameters);
  if (item !== null && Array.isArray(item.parameters)) lists.push(item.parameters);
  return lists;
}

function parameter(spec: Spec, operation: string, location: string, name: string): Record<string, unknown> | null {
  for (const list of parameterLists(spec, operation)) {
    if (!Array.isArray(list)) continue;
    for (const entry of list) {
      const node = deref(spec, entry);
      if (node.in === location && node.name === name) return node;
    }
  }
  return null;
}

function parameterSchema(spec: Spec, operation: string, location: string, name: string): Record<string, unknown> | null {
  const node = parameter(spec, operation, location, name);
  if (node === null || node.schema === undefined) return null;
  return deref(spec, node.schema);
}

function queryNames(spec: Spec, operation: string): Set<string> {
  const names = new Set<string>();
  for (const list of parameterLists(spec, operation)) {
    if (!Array.isArray(list)) continue;
    for (const entry of list) {
      const node = deref(spec, entry);
      if (node.in === 'query' && typeof node.name === 'string') names.add(node.name);
    }
  }
  return names;
}

function requestBodySchema(spec: Spec, operation: string): Record<string, unknown> | null {
  const op = findOperation(spec, operation);
  if (op === null) return null;
  const body = deref(spec, op.requestBody);
  const content = body.content;
  if (!isRecord(content)) return null;
  const media = content['application/json'];
  if (!isRecord(media) || media.schema === undefined) return null;
  return deref(spec, media.schema);
}

function operationDocumented(spec: Spec, operation: string): boolean {
  const op = findOperation(spec, operation);
  return op !== null && isDocumented(spec, op);
}

function operationsOf(result: CallResult): string[] {
  const seen: string[] = [];
  for (const request of result.requests) {
    if (request.operation !== null && !seen.includes(request.operation)) seen.push(request.operation);
  }
  return seen;
}

function label(operations: string[]): string {
  return operations.length === 0 ? '(none)' : operations.join(',');
}

function requestChecks(spec: Spec, tool: string, variant: string, baseline: CallResult): Finding[] {
  const out: Finding[] = [];
  for (const request of baseline.requests) {
    if (request.operation === null) {
      out.push(finding(tool, variant, `${request.method} ${request.path}`, 'baseline', 'undocumented_operation', '', true));
      continue;
    }
    const operation = request.operation;
    const allowed = queryNames(spec, operation);
    for (const [name] of request.query) {
      if (!allowed.has(name)) out.push(finding(tool, variant, operation, 'baseline', 'undocumented_param', name, true));
    }
    const schema = requestBodySchema(spec, operation);
    if (schema === null || request.body === undefined) continue;
    for (const problem of validate(spec, schema, request.body)) {
      const suffix = ':undocumented';
      if (problem.endsWith(suffix)) {
        out.push(finding(tool, variant, operation, 'baseline', 'undocumented_field', problem.slice(0, -suffix.length), true));
      } else {
        out.push(finding(tool, variant, operation, 'baseline', 'request_invalid', problem, true));
      }
    }
  }
  return out;
}

async function responseMutations(
  session: Session,
  spec: Spec,
  tool: string,
  fixture: Fixture,
  baseline: CallResult,
): Promise<StepRun> {
  const findings: Finding[] = [];
  let runs = 0;
  let requests = 0;
  const seen = new Set(baseline.outcomes.map((outcome) => `${outcome.outcome}\u0000${outcome.detail}`));
  for (const operation of operationsOf(baseline)) {
    const op = findOperation(spec, operation);
    if (op === null) continue;
    const success = successResponse(spec, op);
    if (success === null || success.schema === null) continue;
    if (!isConstrained(spec, success.schema)) continue;
    const base = example(spec, success.schema);
    for (const mutation of mutations(spec, success.schema)) {
      const result = await session.call(tool, fixture.args, new Map([[operation, apply(base, mutation)]]));
      runs += 1;
      requests += result.requests.length;
      if (result.rejected !== null) continue;
      for (const outcome of result.outcomes) {
        if (seen.has(`${outcome.outcome}\u0000${outcome.detail}`)) continue;
        findings.push(
          finding(tool, fixture.variant, operation, mutation.id, outcome.outcome, outcome.detail, true),
        );
      }
    }
  }
  return { findings, runs, requests };
}

function violating(keyword: string, limit: unknown, argValue: string | number): string | number | undefined {
  if (keyword === 'enum') return typeof argValue === 'string' && Array.isArray(limit) ? 'zz-invalid' : undefined;
  if (keyword === 'maximum') return typeof argValue === 'number' && typeof limit === 'number' ? limit + 1 : undefined;
  if (keyword === 'minimum') return typeof argValue === 'number' && typeof limit === 'number' ? limit - 1 : undefined;
  if (keyword === 'maxLength') return typeof argValue === 'string' && typeof limit === 'number' ? 'a'.repeat(limit + 1) : undefined;
  return undefined;
}

function collectProbes(spec: Spec, args: Record<string, unknown>, baseline: CallResult): Probe[] {
  const probes: Probe[] = [];
  const seen = new Set<string>();
  const add = (field: string, fieldValue: string, operation: string, limits: Constraints): void => {
    for (const keyword of KEYWORDS) {
      const limit: unknown = limits[keyword];
      for (const [argName, argValue] of Object.entries(args)) {
        if (typeof argValue !== 'string' && typeof argValue !== 'number') continue;
        if (String(argValue) !== fieldValue) continue;
        const value = violating(keyword, limit, argValue);
        if (value === undefined) continue;
        const key = `${argName}\u0000${keyword}\u0000${operation}\u0000${field}`;
        if (seen.has(key)) continue;
        seen.add(key);
        probes.push({ arg: argName, keyword, operation, field, value });
      }
    }
  };
  for (const request of baseline.requests) {
    if (request.operation === null) continue;
    const operation = request.operation;
    for (const [name, value] of request.query) {
      const schema = parameterSchema(spec, operation, 'query', name);
      if (schema === null) continue;
      add(name, value, operation, constraints(spec, schema));
    }
    const body = requestBodySchema(spec, operation);
    if (body === null || !isRecord(request.body)) continue;
    const shape = effective(spec, body);
    const properties = isRecord(shape.properties) ? shape.properties : {};
    for (const [key, schema] of Object.entries(properties)) {
      if (!(key in request.body)) continue;
      add(key, String(request.body[key]), operation, constraints(spec, schema));
    }
  }
  return probes;
}

function carries(request: RequestRecord, field: string, value: string | number): boolean {
  for (const [name, entry] of request.query) {
    if (name === field && entry === String(value)) return true;
  }
  return isRecord(request.body) && request.body[field] === value;
}

async function inputProbes(
  session: Session,
  spec: Spec,
  tool: string,
  fixture: Fixture,
  baseline: CallResult,
): Promise<StepRun> {
  const findings: Finding[] = [];
  let runs = 0;
  let requests = 0;
  for (const probe of collectProbes(spec, fixture.args, baseline)) {
    const args = { ...fixture.args, [probe.arg]: probe.value };
    const result = await session.call(tool, args);
    runs += 1;
    requests += result.requests.length;
    if (result.rejected !== null) continue;
    const reached = result.requests.some(
      (request) => request.operation === probe.operation && carries(request, probe.field, probe.value),
    );
    if (!reached) continue;
    findings.push(
      finding(
        tool,
        fixture.variant,
        probe.operation,
        `input:${probe.arg}=${probe.keyword}`,
        'input_not_enforced',
        `${probe.field}:${probe.keyword}`,
        true,
      ),
    );
  }
  return { findings, runs, requests };
}

async function scanVariant(session: Session, spec: Spec, tool: string, fixture: Fixture): Promise<VariantRun> {
  const findings: Finding[] = [];
  const baseline = await session.call(tool, fixture.args);
  let runs = 1;
  let requests = baseline.requests.length;
  if (baseline.rejected !== null) {
    return { findings, rejected: { tool, variant: fixture.variant, detail: baseline.rejected }, runs, requests };
  }

  const operations = operationsOf(baseline);
  const documented = baseline.requests.every(
    (request) => request.operation !== null && operationDocumented(spec, request.operation),
  );
  for (const outcome of baseline.outcomes) {
    findings.push(finding(tool, fixture.variant, label(operations), 'baseline', outcome.outcome, outcome.detail, documented));
  }
  findings.push(...requestChecks(spec, tool, fixture.variant, baseline));

  const mutated = await responseMutations(session, spec, tool, fixture, baseline);
  runs += mutated.runs;
  requests += mutated.requests;
  findings.push(...mutated.findings);

  const probed = await inputProbes(session, spec, tool, fixture, baseline);
  runs += probed.runs;
  requests += probed.requests;
  findings.push(...probed.findings);

  return { findings, rejected: null, runs, requests };
}

function fields(item: Finding): string[] {
  return [item.tool, item.variant, item.operation, item.mutation, item.outcome, item.detail];
}

function compare(left: Finding, right: Finding): number {
  const a = fields(left);
  const b = fields(right);
  for (let i = 0; i < a.length; i += 1) {
    if (a[i] < b[i]) return -1;
    if (a[i] > b[i]) return 1;
  }
  return 0;
}

function unique(findings: Finding[]): Finding[] {
  const seen = new Set<string>();
  const kept: Finding[] = [];
  for (const item of findings) {
    const key = fields(item).join('\u0000');
    if (seen.has(key)) continue;
    seen.add(key);
    kept.push(item);
  }
  kept.sort(compare);
  return kept;
}

async function main(): Promise<void> {
  const [sourceDir, specPath, inputsPath] = process.argv.slice(2);
  if (sourceDir === undefined || specPath === undefined || inputsPath === undefined) {
    throw new Error('usage: cli.ts SOURCE_DIR SPEC_JSON INPUTS_JSON');
  }
  const spec = readJson(specPath) as Spec;
  const inputs = readJson(inputsPath) as Inputs;
  const session = await loadCommit(sourceDir, spec);

  const findings: Finding[] = [];
  const rejected: Rejected[] = [];
  const untested: string[] = [];
  let runs = 0;
  let requests = 0;

  for (const tool of session.tools) {
    const fixtures = inputs.tools[tool.name] ?? [];
    if (fixtures.length === 0) {
      untested.push(tool.name);
      continue;
    }
    for (const fixture of fixtures) {
      const run = await scanVariant(session, spec, tool.name, fixture);
      runs += run.runs;
      requests += run.requests;
      findings.push(...run.findings);
      if (run.rejected !== null) rejected.push(run.rejected);
    }
  }

  const report = {
    commit: basename(sourceDir),
    tools: session.tools.map((tool) => tool.name),
    untested_tools: untested,
    rejected,
    runs,
    requests,
    findings: unique(findings),
  };
  process.stdout.write(`${JSON.stringify(report)}\n`);
}

main().catch((error: unknown) => {
  process.stderr.write(`${error instanceof Error ? error.stack ?? error.message : String(error)}\n`);
  process.exit(1);
});
