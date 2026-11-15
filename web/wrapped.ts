/** Measures how much text a tool adds to a prompt, and whether an accepted prompt can then exceed the spec limit. */
import { constraints, effective } from './openapi.ts';
import type { Spec } from './openapi.ts';
import { isRecord, requestBodySchema } from './probes.ts';
import type { CallResult, Session } from './harness.ts';

export type Wrap = { operation: string; added: number; threshold: number; overBy: number };

function sentPrompt(result: CallResult, field: string): { operation: string; length: number } | null {
  for (const request of result.requests) {
    if (request.operation === null || !isRecord(request.body)) continue;
    const value = request.body[field];
    if (typeof value === 'string') return { operation: request.operation, length: value.length };
  }
  return null;
}

function documentedMax(spec: Spec, operation: string, field: string): number | null {
  const body = requestBodySchema(spec, operation);
  const properties = body === null ? {} : effective(spec, body).properties;
  const schema = isRecord(properties) ? properties[field] : undefined;
  return schema === undefined ? null : (constraints(spec, schema).maxLength ?? null);
}

/** The length the spec allows minus what the tool adds is the longest safe prompt. A longer accepted prompt goes out over the limit. */
export async function measureWrap(
  session: Session,
  spec: Spec,
  tool: string,
  args: Record<string, unknown>,
): Promise<Wrap | null> {
  const call = (prompt: string): Promise<CallResult> =>
    session.call(tool, { ...args, voice_mode: 'hosted', system_prompt: prompt });
  const probe = sentPrompt(await call('a'), 'systemPrompt');
  if (probe === null) return null;
  const limit = documentedMax(spec, probe.operation, 'systemPrompt');
  if (limit === null) return null;
  const added = probe.length - 1;
  const threshold = limit - added;
  const result = await call('a'.repeat(threshold + 1));
  const sent = result.rejected === null ? sentPrompt(result, 'systemPrompt') : null;
  if (sent === null || sent.length <= limit) return null;
  return { operation: probe.operation, added, threshold, overBy: sent.length - limit };
}
