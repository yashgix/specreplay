/** Scans one source folder against the pinned spec and prints the JSON report. */
import { readFileSync } from 'node:fs';
import {
  apply,
  deref,
  example,
  isConstrained,
  isDocumented,
  mutations,
  successResponse,
  validate,
} from './openapi.ts';
import type { Spec } from './openapi.ts';
import { findOperation } from './fakeapi.ts';
import type { RequestRecord } from './fakeapi.ts';
import { loadCommit } from './harness.ts';
import type { CallResult, Session } from './harness.ts';
import type { Probe } from './probes.ts';
import { measureWrap } from './wrapped.ts';
import { carries, isRecord, collectProbes, parameterLists, parameterSchema, requestBodySchema } from './probes.ts';

type Finding = {
  tool: string;
  variant: string;
  operation: string;
  mutation: string;
  outcome: string;
  detail: string;
  documented: boolean;
};

const SENTINELS = [7, 'probe-value'];
const WIDE = process.env.SPECREPLAY_WIDE === '1';
const probeLog: Record<string, string | boolean>[] = [];

type Rejected = { tool: string; variant: string; detail: string };
type Fixture = { variant: string; args: Record<string, unknown> };
type Inputs = { tools: Record<string, Fixture[]> };
type StepRun = { findings: Finding[]; runs: number; requests: number };
type VariantRun = { findings: Finding[]; rejected: Rejected | null; runs: number; requests: number };

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

async function probeAll(
  session: Session,
  tool: string,
  fixture: Fixture,
  base: Record<string, unknown>,
  probes: Probe[],
  prefix: string,
): Promise<StepRun> {
  const findings: Finding[] = [];
  let runs = 0;
  let requests = 0;
  for (const probe of probes) {
    const result = await session.call(tool, { ...base, [probe.arg]: probe.value });
    runs += 1;
    requests += result.requests.length;
    const reached =
      result.rejected === null &&
      result.requests.some((request) => request.operation === probe.operation && carries(request, probe.field, probe.value));
    probeLog.push({ tool, variant: fixture.variant, arg: probe.arg, keyword: probe.keyword, field: probe.field, mode: prefix, enforced: !reached });
    if (!reached) continue;
    const mutation = `${prefix}:${probe.arg}=${probe.keyword}`;
    findings.push(
      finding(tool, fixture.variant, probe.operation, mutation, 'input_not_enforced', `${probe.field}:${probe.keyword}`, true),
    );
  }
  return { findings, runs, requests };
}

function inputProbes(session: Session, spec: Spec, tool: string, fixture: Fixture, baseline: CallResult): Promise<StepRun> {
  const probes = collectProbes(spec, fixture.args, baseline);
  return probeAll(session, tool, fixture, fixture.args, probes, 'input');
}

/** Wide mode: every argument the fixture leaves out is set to a sentinel, and probed if it reaches a constrained field. */
async function wideProbes(session: Session, spec: Spec, tool: string, fixture: Fixture): Promise<StepRun> {
  const shape = session.tools.find((item) => item.name === tool)?.shape ?? {};
  const total: StepRun = { findings: [], runs: 0, requests: 0 };
  for (const name of Object.keys(shape).filter((key) => !(key in fixture.args))) {
    for (const sentinel of SENTINELS) {
      const base = { ...fixture.args, [name]: sentinel };
      const result = await session.call(tool, base);
      total.runs += 1;
      if (result.rejected !== null) continue;
      const probed = await probeAll(session, tool, fixture, base, collectProbes(spec, { [name]: sentinel }, result), 'wide');
      total.findings.push(...probed.findings);
      total.runs += probed.runs;
      total.requests += probed.requests + result.requests.length;
      break;
    }
  }
  return total;
}

async function wrapFindings(session: Session, spec: Spec, tool: string, fixture: Fixture): Promise<StepRun> {
  const none: StepRun = { findings: [], runs: 0, requests: 0 };
  if (!('system_prompt' in (session.tools.find((item) => item.name === tool)?.shape ?? {}))) return none;
  const { wrap, calls, requests } = await measureWrap(session, spec, tool, fixture.args);
  if (wrap === null) return { ...none, runs: calls, requests };
  const detail = `systemPrompt:maxLength added=${wrap.added} threshold=${wrap.threshold}`;
  const found = finding(tool, fixture.variant, wrap.operation, 'wide:system_prompt=wrapped', 'wrapped_over_limit', detail, true);
  return { findings: [found], runs: calls, requests };
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

  if (WIDE) {
    for (const step of [await wideProbes(session, spec, tool, fixture), await wrapFindings(session, spec, tool, fixture)]) {
      runs += step.runs;
      requests += step.requests;
      findings.push(...step.findings);
    }
  }

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

const METHODS = ['get', 'put', 'post', 'delete', 'options', 'head', 'patch', 'trace'];

/** Operations whose generated success response breaks its own schema. A replay on them would blame the tool for the fake. */
function invalidBaselines(spec: Spec): string[] {
  const bad: string[] = [];
  const paths = isRecord(spec.paths) ? spec.paths : {};
  for (const [path, item] of Object.entries(paths)) {
    for (const method of METHODS) {
      const operation = isRecord(item) ? item[method] : undefined;
      const success = operation === undefined ? null : successResponse(spec, operation);
      if (success === null || success.schema === null || !isConstrained(spec, success.schema)) continue;
      const problems = validate(spec, success.schema, example(spec, success.schema));
      if (problems.length > 0) bad.push(`${method.toUpperCase()} ${path} ${problems.join(',')}`);
    }
  }
  return bad;
}

async function main(): Promise<void> {
  const [sourceDir, specPath, inputsPath] = process.argv.slice(2);
  if (sourceDir === undefined || specPath === undefined || inputsPath === undefined) {
    throw new Error('usage: cli.ts SOURCE_DIR SPEC_JSON INPUTS_JSON');
  }
  const spec = readJson(specPath) as Spec;
  const inputs = readJson(inputsPath) as Inputs;
  const bad = invalidBaselines(spec);
  if (bad.length > 0) throw new Error(`generated baselines break their own schema: ${bad.join('; ')}`);
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
    ...(WIDE ? { probes: probeLog } : {}),
  };
  process.stdout.write(`${JSON.stringify(report)}\n`);
}

main().catch((error: unknown) => {
  process.stderr.write(`${error instanceof Error ? error.stack ?? error.message : String(error)}\n`);
  process.exit(1);
});
