/** Helpers for reading the pinned OpenAPI document. */

export type Spec = Record<string, unknown>;
export type Schema = Record<string, unknown>;
export type Success = { status: number; schema: Schema | null };
export type MutationKind = 'null' | 'alt' | 'enum' | 'empty_array' | 'omit';
export type Mutation = { id: string; path: string; kind: MutationKind; value?: unknown };
export type Constraints = { enum?: unknown[]; maximum?: number; minimum?: number; maxLength?: number };

const ANNOTATION_KEYS = new Set(['title', 'description', 'examples', 'example', 'default']);

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function has(record: Record<string, unknown>, key: string): boolean {
  return Object.prototype.hasOwnProperty.call(record, key);
}

function asRecord(value: unknown): Record<string, unknown> {
  return isRecord(value) ? value : {};
}

function clone(value: unknown): unknown {
  if (Array.isArray(value)) return value.map((item) => clone(item));
  if (isRecord(value)) {
    const out: Record<string, unknown> = {};
    for (const [key, item] of Object.entries(value)) out[key] = clone(item);
    return out;
  }
  return value;
}

function resolvePointer(spec: Spec, ref: string): unknown {
  if (!ref.startsWith('#/')) return undefined;
  let current: unknown = spec;
  for (const raw of ref.slice(2).split('/')) {
    const part = raw.replace(/~1/g, '/').replace(/~0/g, '~');
    if (!isRecord(current) || !has(current, part)) return undefined;
    current = current[part];
  }
  return current;
}

export function deref(spec: Spec, schema: unknown): Schema {
  let current: unknown = schema;
  const seen = new Set<string>();
  while (isRecord(current) && typeof current.$ref === 'string') {
    const ref = current.$ref;
    if (seen.has(ref)) return {};
    seen.add(ref);
    current = resolvePointer(spec, ref);
  }
  return isRecord(current) ? current : {};
}

function withEnum(base: Schema, node: Schema): Schema {
  return has(node, 'enum') ? { ...base, enum: node.enum } : base;
}

function isNullSchema(spec: Spec, schema: unknown): boolean {
  return deref(spec, schema).type === 'null';
}

function effectiveAt(spec: Spec, schema: unknown, depth: number): Schema {
  const node = deref(spec, schema);
  if (depth >= 12) return node;
  if (Array.isArray(node.anyOf)) {
    const nonNull = node.anyOf.filter((branch) => !isNullSchema(spec, branch));
    if (nonNull.length === 0) return withEnum({ type: 'null' }, node);
    return withEnum(effectiveAt(spec, nonNull[0], depth + 1), node);
  }
  if (Array.isArray(node.allOf) && node.allOf.length > 0) {
    return withEnum(effectiveAt(spec, node.allOf[0], depth + 1), node);
  }
  return node;
}

export function effective(spec: Spec, schema: unknown): Schema {
  return effectiveAt(spec, schema, 0);
}

function isTemplateSegment(segment: string): boolean {
  return segment.length > 2 && segment.startsWith('{') && segment.endsWith('}');
}

export function matchOperation(spec: Spec, method: string, path: string): string | null {
  const paths = isRecord(spec.paths) ? spec.paths : {};
  const wanted = path.split('/').slice(1);
  const wantedMethod = method.toUpperCase();
  let best: { name: string; literals: number } | null = null;
  for (const [template, item] of Object.entries(paths)) {
    if (!isRecord(item) || !isRecord(item[method.toLowerCase()])) continue;
    const parts = template.split('/').slice(1);
    if (parts.length !== wanted.length) continue;
    let ok = true;
    let literals = 0;
    for (let i = 0; i < parts.length; i += 1) {
      const part = parts[i];
      const value = wanted[i];
      if (isTemplateSegment(part)) {
        if (value.length === 0) {
          ok = false;
          break;
        }
      } else if (part !== value) {
        ok = false;
        break;
      } else {
        literals += 1;
      }
    }
    if (ok && (best === null || literals > best.literals)) {
      best = { name: `${wantedMethod} ${template}`, literals };
    }
  }
  return best === null ? null : best.name;
}

export function successStatus(operation: unknown, maybeOperation?: unknown): number | null {
  const op = asRecord(maybeOperation === undefined ? operation : maybeOperation);
  const responses = asRecord(op.responses);
  const codes = Object.keys(responses)
    .filter((code) => code.length === 3 && code.startsWith('2') && Number.isInteger(Number(code)))
    .map(Number)
    .sort((a, b) => a - b);
  const first = codes[0];
  return first === undefined ? null : first;
}

export function successResponse(spec: Spec, operation: unknown): Success | null {
  const status = successStatus(operation);
  if (status === null) return null;
  const op = asRecord(operation);
  const responses = asRecord(op.responses);
  const response = deref(spec, responses[String(status)]);
  const content = asRecord(response.content);
  const media = content['application/json'];
  if (!isRecord(media)) return { status, schema: null };
  const schema = has(media, 'schema') ? media.schema : {};
  return { status, schema: deref(spec, schema) };
}

export function isConstrained(spec: Spec, schema: unknown): boolean {
  const node = deref(spec, schema);
  return Object.keys(node).some((key) => !ANNOTATION_KEYS.has(key));
}

export function isDocumented(spec: Spec, operation: unknown): boolean {
  const success = successResponse(spec, operation);
  return success !== null && (success.schema === null || isConstrained(spec, success.schema));
}

export const documented = isDocumented;

function typesOf(schema: Schema): string[] {
  const type = schema.type;
  if (typeof type === 'string') return [type];
  if (Array.isArray(type)) return type.filter((item): item is string => typeof item === 'string');
  return [];
}

function fitsType(type: string, value: unknown): boolean {
  switch (type) {
    case 'string':
      return typeof value === 'string';
    case 'number':
      return typeof value === 'number';
    case 'integer':
      return typeof value === 'number' && Number.isInteger(value);
    case 'boolean':
      return typeof value === 'boolean';
    case 'array':
      return Array.isArray(value);
    case 'object':
      return isRecord(value);
    case 'null':
      return value === null;
    default:
      return true;
  }
}

function typeFitsSchema(schema: Schema, value: unknown): boolean {
  const types = typesOf(schema);
  return types.length === 0 || types.some((type) => fitsType(type, value));
}

function stringExample(format: unknown): string {
  switch (format) {
    case 'date-time':
      return '2026-01-01T00:00:00Z';
    case 'date':
      return '2026-01-01';
    case 'uri':
      return 'https://example.com/';
    case 'email':
      return 'user@example.com';
    default:
      return 'text';
  }
}

export function example(spec: Spec, schema: unknown, depth = 0): unknown {
  if (depth >= 12) return null;
  const node = effective(spec, schema);
  if (Array.isArray(node.enum) && node.enum.length > 0) return node.enum[0];
  if (has(node, 'const')) return node.const;
  const properties = node.properties;
  if (isRecord(properties)) {
    const out: Record<string, unknown> = {};
    for (const [key, property] of Object.entries(properties)) out[key] = example(spec, property, depth + 1);
    return out;
  }
  const types = typesOf(node);
  if (types.includes('array')) {
    if (!has(node, 'items')) return [];
    return [example(spec, node.items, depth + 1)];
  }
  if (types.includes('string')) return stringExample(node.format);
  if (types.includes('integer') || types.includes('number')) {
    return typeof node.minimum === 'number' ? node.minimum : 1;
  }
  if (types.includes('boolean')) return true;
  if (types.includes('null')) return null;
  return {};
}

function mutationsAt(spec: Spec, schema: unknown, path: string, depth: number): Mutation[] {
  if (depth >= 12) return [];
  const node = deref(spec, schema);
  const shape = effective(spec, schema);
  const out: Mutation[] = [];
  if (Array.isArray(node.anyOf)) {
    const nonNull = node.anyOf.filter((branch) => !isNullSchema(spec, branch));
    if (nonNull.length > 0 && nonNull.length < node.anyOf.length) {
      out.push({ id: `null:${path}`, path, kind: 'null' });
    }
    for (let i = 1; i < nonNull.length; i += 1) {
      out.push({ id: `alt:${path}#${i}`, path, kind: 'alt', value: example(spec, nonNull[i], depth + 1) });
    }
  }
  if (Array.isArray(shape.enum)) {
    for (let i = 1; i < shape.enum.length; i += 1) {
      out.push({ id: `enum:${path}=${String(shape.enum[i])}`, path, kind: 'enum', value: shape.enum[i] });
    }
  }
  if (has(shape, 'items')) {
    out.push({ id: `empty_array:${path}`, path, kind: 'empty_array' });
    out.push(...mutationsAt(spec, shape.items, `${path}[0]`, depth + 1));
  }
  const properties = shape.properties;
  if (isRecord(properties)) {
    const required = new Set(
      Array.isArray(shape.required)
        ? shape.required.filter((key): key is string => typeof key === 'string')
        : []
    );
    for (const [key, property] of Object.entries(properties)) {
      const childPath = `${path}.${key}`;
      const propertyNode = deref(spec, property);
      const defaulted = (isRecord(property) && has(property, 'default')) || has(propertyNode, 'default');
      if (!required.has(key) && !defaulted) out.push({ id: `omit:${childPath}`, path: childPath, kind: 'omit' });
      out.push(...mutationsAt(spec, property, childPath, depth + 1));
    }
  }
  return out;
}

export function mutations(spec: Spec, schema: unknown): Mutation[] {
  return mutationsAt(spec, schema, '$', 0);
}

type PathPart = string | number;

function parsePath(path: string): PathPart[] {
  const parts: PathPart[] = [];
  let i = path.startsWith('$') ? 1 : 0;
  while (i < path.length) {
    const ch = path[i];
    if (ch === '.') {
      i += 1;
      const start = i;
      while (i < path.length && path[i] !== '.' && path[i] !== '[') i += 1;
      if (i > start) parts.push(path.slice(start, i));
    } else if (ch === '[') {
      const end = path.indexOf(']', i);
      if (end < 0) break;
      const index = Number(path.slice(i + 1, end));
      if (!Number.isNaN(index)) parts.push(index);
      i = end + 1;
    } else {
      i += 1;
    }
  }
  return parts;
}

function childAt(parent: unknown, part: PathPart): unknown {
  if (Array.isArray(parent) && typeof part === 'number') return parent[part];
  if (isRecord(parent) && typeof part === 'string') return parent[part];
  return undefined;
}

function replacement(mutation: Mutation): unknown {
  if (mutation.kind === 'null') return null;
  if (mutation.kind === 'empty_array') return [];
  return clone(mutation.value);
}

export function apply(exampleValue: unknown, mutation: Mutation): unknown {
  const copy = clone(exampleValue);
  const parts = parsePath(mutation.path);
  if (parts.length === 0) return mutation.kind === 'omit' ? copy : replacement(mutation);
  let parent: unknown = copy;
  for (let i = 0; i < parts.length - 1; i += 1) parent = childAt(parent, parts[i]);
  const last = parts[parts.length - 1];
  if (Array.isArray(parent) && typeof last === 'number') {
    if (mutation.kind === 'omit') parent.splice(last, 1);
    else parent[last] = replacement(mutation);
  } else if (isRecord(parent) && typeof last === 'string') {
    if (mutation.kind === 'omit') delete parent[last];
    else parent[last] = replacement(mutation);
  }
  return copy;
}

function sameValue(left: unknown, right: unknown): boolean {
  if (left === right) return true;
  if (Array.isArray(left) && Array.isArray(right)) {
    return left.length === right.length && left.every((item, index) => sameValue(item, right[index]));
  }
  if (isRecord(left) && isRecord(right)) {
    const keys = Object.keys(left);
    return keys.length === Object.keys(right).length && keys.every((key) => has(right, key) && sameValue(left[key], right[key]));
  }
  return false;
}

function enumHas(values: unknown[], value: unknown): boolean {
  return values.some((item) => sameValue(item, value));
}

function validateAt(spec: Spec, schema: unknown, value: unknown, path: string, depth: number): string[] {
  if (depth >= 12) return [];
  const node = deref(spec, schema);
  if (Array.isArray(node.anyOf)) {
    const branch = node.anyOf.find((candidate) => typeFitsSchema(deref(spec, candidate), value));
    if (branch === undefined) return [`${path}:type`];
    const problems = validateAt(spec, branch, value, path, depth + 1);
    if (value !== null && Array.isArray(node.enum) && !enumHas(node.enum, value)) problems.push(`${path}:enum`);
    return problems;
  }
  const shape = effective(spec, schema);
  const types = typesOf(shape);
  if (types.length > 0 && !types.some((type) => fitsType(type, value))) return [`${path}:type`];
  const problems: string[] = [];
  if (Array.isArray(shape.enum) && !enumHas(shape.enum, value)) problems.push(`${path}:enum`);
  if (typeof value === 'string') {
    if (typeof shape.maxLength === 'number' && value.length > shape.maxLength) problems.push(`${path}:maxLength`);
    if (typeof shape.minLength === 'number' && value.length < shape.minLength) problems.push(`${path}:minLength`);
  }
  if (typeof value === 'number') {
    if (typeof shape.maximum === 'number' && value > shape.maximum) problems.push(`${path}:maximum`);
    if (typeof shape.minimum === 'number' && value < shape.minimum) problems.push(`${path}:minimum`);
  }
  if (Array.isArray(value)) {
    if (typeof shape.maxItems === 'number' && value.length > shape.maxItems) problems.push(`${path}:maxItems`);
    if (typeof shape.minItems === 'number' && value.length < shape.minItems) problems.push(`${path}:minItems`);
    if (has(shape, 'items')) {
      for (let i = 0; i < value.length; i += 1) {
        problems.push(...validateAt(spec, shape.items, value[i], `${path}[${i}]`, depth + 1));
      }
    }
  }
  const properties = shape.properties;
  if (isRecord(value) && isRecord(properties)) {
    const required = Array.isArray(shape.required)
      ? shape.required.filter((key): key is string => typeof key === 'string')
      : [];
    for (const key of required) {
      if (!has(value, key)) problems.push(`${path}.${key}:required`);
    }
    for (const key of Object.keys(value)) {
      if (has(properties, key)) {
        problems.push(...validateAt(spec, properties[key], value[key], `${path}.${key}`, depth + 1));
      } else if (!shape.additionalProperties) {
        problems.push(`${path}.${key}:undocumented`);
      }
    }
  }
  return problems;
}

export function validate(spec: Spec, schema: unknown, value: unknown): string[] {
  return validateAt(spec, schema, value, '$', 0);
}

export function constraints(spec: Spec, schema: unknown): Constraints {
  const shape = effective(spec, schema);
  const out: Constraints = {};
  if (Array.isArray(shape.enum)) out.enum = shape.enum;
  if (typeof shape.maximum === 'number') out.maximum = shape.maximum;
  if (typeof shape.minimum === 'number') out.minimum = shape.minimum;
  if (typeof shape.maxLength === 'number') out.maxLength = shape.maxLength;
  return out;
}
