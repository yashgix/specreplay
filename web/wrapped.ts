/** Measures how much text a tool adds to a prompt, and whether an accepted prompt can then exceed the spec limit. */
import { characters, constraints, effective } from './openapi.ts';
import type { Spec } from './openapi.ts';
import { isRecord, requestBodySchema } from './probes.ts';
import type { CallResult, Session } from './harness.ts';

export type Wrap = { operation: string; added: number; threshold: number; overBy: number };

function sentPrompt(result: CallResult, field: string): { operation: string; length: number } | null {
  for (const request of result.requests) {
    if (request.operation === null || !isRecord(request.body)) continue;
    const value = request.body[field];
    if (typeof value === 'string') return { operation: request.operation, length: characters(value) };
  }
  return null;
}

function documentedMax(spec: Spec, operation: string, field: string): number | null {
  const body = requestBodySchema(spec, operation);
  const properties = body === null ? {} : effective(spec, body).properties;
  const schema = isRecord(properties) ? properties[field] : undefined;
  return schema === undefined ? null : (constraints(spec, schema).maxLength ?? null);
}

export type Measured = { wrap: Wrap | null; calls: number; requests: number };

/**
 * The limit minus what the tool adds is the longest hosted prompt that still fits. The length is measured with plain
 * ASCII prompts, so it holds for text that needs no trimming and is not already wrapped. A prompt one character
 * longer that the tool accepts goes out over the limit.
 */
export async function measureWrap(session: Session, spec: Spec, tool: string, args: Record<string, unknown>): Promise<Measured> {
  const total: Measured = { wrap: null, calls: 0, requests: 0 };
  const call = async (prompt: string): Promise<CallResult> => {
    const result = await session.call(tool, { ...args, voice_mode: 'hosted', system_prompt: prompt });
    total.calls += 1;
    total.requests += result.requests.length;
    return result;
  };
  const probe = sentPrompt(await call('a'), 'systemPrompt');
  const limit = probe === null ? null : documentedMax(spec, probe.operation, 'systemPrompt');
  if (probe === null || limit === null) return total;
  const added = probe.length - 1;
  const threshold = limit - added;
  const result = await call('a'.repeat(threshold + 1));
  const sent = result.rejected === null ? sentPrompt(result, 'systemPrompt') : null;
  if (sent === null || sent.length <= limit) return total;
  total.wrap = { operation: probe.operation, added, threshold, overBy: sent.length - limit };
  return total;
}
