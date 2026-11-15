/** Finds the tool arguments that reach a constrained request field, and the value just outside its limit. */
import { constraints, deref, effective } from './openapi.ts';
import type { Constraints, Spec } from './openapi.ts';
import { findOperation } from './fakeapi.ts';
import type { RequestRecord } from './fakeapi.ts';
import type { CallResult } from './harness.ts';

export type Probe = { arg: string; keyword: string; operation: string; field: string; value: string | number };

const KEYWORDS = ['enum', 'maximum', 'minimum', 'maxLength'] as const;

export function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function pathItem(spec: Spec, operation: string): Record<string, unknown> | null {
  const space = operation.indexOf(' ');
  if (space < 0) return null;
  const paths = isRecord(spec.paths) ? spec.paths : {};
  const item = paths[operation.slice(space + 1)];
  return isRecord(item) ? item : null;
}

export function parameterLists(spec: Spec, operation: string): unknown[] {
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

export function parameterSchema(spec: Spec, operation: string, location: string, name: string): Record<string, unknown> | null {
  const node = parameter(spec, operation, location, name);
  if (node === null || node.schema === undefined) return null;
  return deref(spec, node.schema);
}

export function requestBodySchema(spec: Spec, operation: string): Record<string, unknown> | null {
  const op = findOperation(spec, operation);
  if (op === null) return null;
  const body = deref(spec, op.requestBody);
  const content = body.content;
  if (!isRecord(content)) return null;
  const media = content['application/json'];
  if (!isRecord(media) || media.schema === undefined) return null;
  return deref(spec, media.schema);
}

function violating(keyword: string, limit: unknown, argValue: string | number): string | number | undefined {
  if (keyword === 'enum') return typeof argValue === 'string' && Array.isArray(limit) ? 'zz-invalid' : undefined;
  if (keyword === 'maximum') return typeof argValue === 'number' && typeof limit === 'number' ? limit + 1 : undefined;
  if (keyword === 'minimum') return typeof argValue === 'number' && typeof limit === 'number' ? limit - 1 : undefined;
  if (keyword === 'maxLength') return typeof argValue === 'string' && typeof limit === 'number' ? 'a'.repeat(limit + 1) : undefined;
  return undefined;
}

export function collectProbes(spec: Spec, args: Record<string, unknown>, baseline: CallResult): Probe[] {
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

export function carries(request: RequestRecord, field: string, value: string | number): boolean {
  for (const [name, entry] of request.query) {
    if (name === field && entry === String(value)) return true;
  }
  return isRecord(request.body) && request.body[field] === value;
}
