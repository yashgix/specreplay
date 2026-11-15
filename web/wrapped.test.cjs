'use strict';

const { test } = require('node:test');
const assert = require('node:assert/strict');

const SPEC = {
  paths: {
    '/v1/agents': {
      post: {
        requestBody: { content: { 'application/json': { schema: { type: 'object', properties: { systemPrompt: { type: 'string', maxLength: 100 } } } } } },
      },
    },
  },
};

// A tool that wraps the prompt in a fixed text. The text holds emoji, so UTF-16 units and characters differ.
function session(wrapper, accept = () => true) {
  return {
    tools: [],
    async call(_tool, args) {
      if (!accept(args.system_prompt)) return { rejected: 'input', outcomes: [], requests: [] };
      const body = { systemPrompt: wrapper + args.system_prompt };
      return { rejected: null, outcomes: [], requests: [{ operation: 'POST /v1/agents', body, query: [] }] };
    },
  };
}

let loaded;
async function wrapped() {
  if (loaded === undefined) loaded = await import('./wrapped.ts');
  return loaded;
}

test('the added length is counted in characters and the threshold follows', async () => {
  const { measureWrap } = await wrapped();
  const result = await measureWrap(session('😀'.repeat(10)), SPEC, 'create_agent', {});
  assert.equal(result.wrap.added, 10);
  assert.equal(result.wrap.threshold, 90);
  assert.equal(result.wrap.overBy, 1);
  assert.equal(result.calls, 2);
  assert.equal(result.requests, 2);
});

test('no finding when the tool refuses the prompt that would go over', async () => {
  const { measureWrap } = await wrapped();
  const result = await measureWrap(session('x'.repeat(10), (prompt) => prompt.length <= 90), SPEC, 'create_agent', {});
  assert.equal(result.wrap, null);
  assert.equal(result.calls, 2);
  assert.equal(result.requests, 1);
});
