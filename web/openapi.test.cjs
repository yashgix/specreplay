'use strict';

const { test } = require('node:test');
const assert = require('node:assert/strict');

const SPEC = {
  components: {
    schemas: {
      Pet: { type: 'object', properties: { name: { type: 'string' } } },
      LoopA: { $ref: '#/components/schemas/LoopB' },
      LoopB: { $ref: '#/components/schemas/LoopA' },
    },
    responses: {
      Ok: { content: { 'application/json': { schema: { type: 'string' } } } },
    },
  },
  paths: {},
};

let loaded;
async function openapi() {
  if (loaded === undefined) loaded = await import('./openapi.ts');
  return loaded;
}

test('deref follows refs and stops on a cycle', async () => {
  const { deref } = await openapi();
  assert.deepEqual(deref(SPEC, { $ref: '#/components/schemas/Pet' }), SPEC.components.schemas.Pet);
  assert.deepEqual(deref(SPEC, { $ref: '#/components/schemas/LoopA' }), {});
  assert.deepEqual(deref(SPEC, { $ref: '#/components/schemas/Missing' }), {});
  assert.deepEqual(deref(SPEC, null), {});
  assert.deepEqual(deref(SPEC, { type: 'string' }), { type: 'string' });
});

test('effective picks the first non-null anyOf branch and keeps a sibling enum', async () => {
  const { effective } = await openapi();
  assert.deepEqual(
    effective(SPEC, { anyOf: [{ type: 'string', enum: ['a'] }, { type: 'null' }] }),
    { type: 'string', enum: ['a'] },
  );
  assert.deepEqual(
    effective(SPEC, { anyOf: [{ type: 'string' }, { type: 'null' }], enum: ['x'] }),
    { type: 'string', enum: ['x'] },
  );
  assert.deepEqual(
    effective(SPEC, { allOf: [{ type: 'integer', minimum: 2 }, { type: 'string' }], enum: ['x'] }),
    { type: 'integer', minimum: 2, enum: ['x'] },
  );
  assert.deepEqual(effective(SPEC, { anyOf: [{ type: 'null' }] }), { type: 'null' });
});

test('matchOperation prefers the most literal template and ties by spec order', async () => {
  const { matchOperation } = await openapi();
  const routes = {
    paths: {
      '/v1/{kind}/{id}': { get: {} },
      '/v1/agents/{id}': { get: {} },
      '/v1/agents/me': { get: {} },
    },
  };
  assert.equal(matchOperation(routes, 'get', '/v1/agents/42'), 'GET /v1/agents/{id}');
  assert.equal(matchOperation(routes, 'get', '/v1/agents/me'), 'GET /v1/agents/me');
  assert.equal(matchOperation(routes, 'post', '/v1/agents/42'), null);

  const tie = {
    paths: {
      '/v1/agents/{agent_id}': { get: {} },
      '/v1/{kind}/me': { get: {} },
    },
  };
  assert.equal(matchOperation(tie, 'GET', '/v1/agents/me'), 'GET /v1/agents/{agent_id}');

  const reversed = {
    paths: {
      '/v1/{kind}/me': { get: {} },
      '/v1/agents/{agent_id}': { get: {} },
    },
  };
  assert.equal(matchOperation(reversed, 'GET', '/v1/agents/me'), 'GET /v1/{kind}/me');
  assert.equal(matchOperation(tie, 'GET', '/v1/agents/'), null);
  assert.equal(matchOperation(tie, 'GET', '/v1/agents'), null);
});

test('successResponse separates schema, no-content and unconstrained', async () => {
  const { successResponse, successStatus, isConstrained, isDocumented } = await openapi();

  const noContent = { responses: { '204': {} } };
  assert.deepEqual(successResponse(SPEC, noContent), { status: 204, schema: null });
  assert.equal(isDocumented(SPEC, noContent), true);

  const unconstrained = {
    responses: {
      '200': {
        content: { 'application/json': { schema: { title: 'Thing', description: 'No constraints' } } },
      },
    },
  };
  assert.deepEqual(successResponse(SPEC, unconstrained), {
    status: 200,
    schema: { title: 'Thing', description: 'No constraints' },
  });
  assert.equal(isConstrained(SPEC, { title: 'Thing' }), false);
  assert.equal(isDocumented(SPEC, unconstrained), false);

  const referenced = { responses: { '201': { $ref: '#/components/responses/Ok' } } };
  assert.deepEqual(successResponse(SPEC, referenced), { status: 201, schema: { type: 'string' } });
  assert.equal(isDocumented(SPEC, referenced), true);

  const multi = {
    responses: {
      '202': { description: 'later' },
      '200': { content: { 'application/json': { schema: { type: 'string' } } } },
    },
  };
  assert.equal(successStatus(multi), 200);
  assert.deepEqual(successResponse(SPEC, multi), { status: 200, schema: { type: 'string' } });

  assert.equal(successStatus({ responses: { '404': {} } }), null);
  assert.equal(successResponse(SPEC, { responses: { '404': {} } }), null);
});

test('example builds deterministic values per type and format', async () => {
  const { example } = await openapi();
  const cases = [
    [{ type: 'string' }, 'text'],
    [{ type: 'string', format: 'date-time' }, '2026-01-01T00:00:00Z'],
    [{ type: 'string', format: 'date' }, '2026-01-01'],
    [{ type: 'string', format: 'uri' }, 'https://example.com/'],
    [{ type: 'string', format: 'email' }, 'user@example.com'],
    [{ type: 'integer', minimum: 7 }, 7],
    [{ type: 'number' }, 1],
    [{ type: 'boolean' }, true],
    [{ type: 'null' }, null],
    [{ type: 'string', enum: ['first', 'second'] }, 'first'],
    [{ const: 'fixed' }, 'fixed'],
    [{ type: 'array' }, []],
  ];
  for (const [schema, expected] of cases) assert.deepEqual(example(SPEC, schema), expected);

  assert.deepEqual(example(SPEC, { type: 'array', items: { type: 'integer' } }), [1]);
  assert.deepEqual(
    example(SPEC, { type: 'object', properties: { a: { type: 'string' }, b: { type: 'integer' } } }),
    { a: 'text', b: 1 },
  );
  assert.deepEqual(example(SPEC, { $ref: '#/components/schemas/Pet' }), { name: 'text' });
});

test('example stops below depth 12', async () => {
  const { example } = await openapi();
  assert.equal(example(SPEC, { type: 'string' }, 11), 'text');
  assert.equal(example(SPEC, { type: 'string' }, 12), null);
  const chain = {
    type: 'object',
    properties: { nested: { type: 'object', properties: { deep: { type: 'string' } } } },
  };
  assert.deepEqual(example(SPEC, chain, 9), { nested: { deep: 'text' } });
  assert.deepEqual(example(SPEC, chain, 10), { nested: { deep: null } });
  assert.deepEqual(example(SPEC, chain, 11), { nested: null });
});

test('mutations enumerates single faults in order', async () => {
  const { mutations } = await openapi();
  const schema = {
    type: 'object',
    required: ['id'],
    properties: {
      id: { type: 'integer' },
      meta: {
        anyOf: [{ type: 'object', properties: { a: { type: 'string' } } }, { type: 'null' }],
      },
      items: {
        type: 'array',
        items: {
          type: 'object',
          required: ['name'],
          properties: { name: { type: 'string', default: 'x' }, tag: { type: 'string' } },
        },
      },
      kind: { type: 'string', enum: ['a', 'b', 'c'] },
    },
  };
  assert.deepEqual(mutations({}, schema), [
    { id: 'omit:$.meta', path: '$.meta', kind: 'omit' },
    { id: 'null:$.meta', path: '$.meta', kind: 'null' },
    { id: 'omit:$.meta.a', path: '$.meta.a', kind: 'omit' },
    { id: 'omit:$.items', path: '$.items', kind: 'omit' },
    { id: 'empty_array:$.items', path: '$.items', kind: 'empty_array' },
    { id: 'omit:$.items[0].tag', path: '$.items[0].tag', kind: 'omit' },
    { id: 'omit:$.kind', path: '$.kind', kind: 'omit' },
    { id: 'enum:$.kind=b', path: '$.kind', kind: 'enum', value: 'b' },
    { id: 'enum:$.kind=c', path: '$.kind', kind: 'enum', value: 'c' },
  ]);
});

test('mutations emits null and alternative branches for a union', async () => {
  const { mutations } = await openapi();
  const union = { anyOf: [{ type: 'string' }, { type: 'integer' }, { type: 'null' }, { type: 'boolean' }] };
  const found = mutations({}, union);
  assert.deepEqual(found.map((item) => item.id), ['null:$', 'alt:$#1', 'alt:$#2']);
  assert.deepEqual(found.map((item) => item.value), [undefined, 1, true]);
});

test('apply deletes omitted keys without touching the input', async () => {
  const { apply } = await openapi();
  const base = { id: 1, meta: { a: 'x', b: 'y' }, items: [{ name: 'n', tag: 't' }], kind: 'a' };
  const snapshot = JSON.parse(JSON.stringify(base));

  assert.deepEqual(apply(base, { kind: 'omit', path: '$.meta' }), {
    id: 1,
    items: [{ name: 'n', tag: 't' }],
    kind: 'a',
  });
  assert.deepEqual(base, snapshot);

  assert.deepEqual(apply(base, { kind: 'omit', path: '$.items[0].tag' }), {
    id: 1,
    meta: { a: 'x', b: 'y' },
    items: [{ name: 'n' }],
    kind: 'a',
  });
  assert.deepEqual(base, snapshot);
});

test('apply replaces the whole body at the root', async () => {
  const { apply } = await openapi();
  const base = { id: 1, meta: { a: 'x' } };
  const snapshot = JSON.parse(JSON.stringify(base));
  assert.deepEqual(apply(base, { kind: 'alt', path: '$', value: { z: 1 } }), { z: 1 });
  assert.deepEqual(base, snapshot);
});

test('validate reports type, enum, bounds and array item problems', async () => {
  const { validate } = await openapi();
  assert.deepEqual(validate(SPEC, { type: 'string' }, 5), ['$:type']);
  assert.deepEqual(validate(SPEC, { type: 'number' }, 3), []);
  assert.deepEqual(validate(SPEC, { type: 'integer' }, 3.5), ['$:type']);
  assert.deepEqual(validate(SPEC, { type: 'string', maxLength: 3 }, 'abcd'), ['$:maxLength']);
  assert.deepEqual(validate(SPEC, { type: 'string', minLength: 2 }, 'a'), ['$:minLength']);
  assert.deepEqual(validate(SPEC, { type: 'number', maximum: 5 }, 6), ['$:maximum']);
  assert.deepEqual(validate(SPEC, { type: 'number', minimum: 2 }, 1), ['$:minimum']);
  assert.deepEqual(validate(SPEC, { type: 'string', enum: ['a'] }, 'b'), ['$:enum']);
  assert.deepEqual(
    validate(SPEC, { type: 'array', items: { type: 'number' }, maxItems: 1 }, [1, 2]),
    ['$:maxItems'],
  );
  assert.deepEqual(
    validate(SPEC, { type: 'array', items: { type: 'string' }, minItems: 1 }, []),
    ['$:minItems'],
  );
  assert.deepEqual(validate(SPEC, { type: 'array', items: { type: 'number' } }, [1, 'x', 2]), [
    '$[1]:type',
  ]);
});

test('validate checks anyOf branches and a sibling enum', async () => {
  const { validate } = await openapi();
  const union = { anyOf: [{ type: 'number' }, { type: 'string', maxLength: 2 }], enum: ['a', 3] };
  assert.deepEqual(validate(SPEC, union, 'abc'), ['$:maxLength', '$:enum']);
  assert.deepEqual(validate(SPEC, union, 'a'), []);
  assert.deepEqual(validate(SPEC, union, 'b'), ['$:enum']);
  assert.deepEqual(validate(SPEC, union, true), ['$:type']);
});

test('validate reports required and unknown object keys', async () => {
  const { validate } = await openapi();
  const schema = { type: 'object', properties: { a: { type: 'string' } }, required: ['a', 'b'] };
  assert.deepEqual(validate(SPEC, schema, { a: 'ok', c: 1 }), ['$.b:required', '$.c:undocumented']);
  assert.deepEqual(validate(SPEC, { ...schema, additionalProperties: true }, { a: 'ok', c: 1 }), [
    '$.b:required',
  ]);
  assert.deepEqual(validate(SPEC, { type: 'object', properties: { a: { type: 'string' } } }, { a: 5 }), [
    '$.a:type',
  ]);
});

test('constraints extracts the effective limits', async () => {
  const { constraints } = await openapi();
  assert.deepEqual(constraints(SPEC, { type: 'string', maxLength: 5 }), { maxLength: 5 });
  assert.deepEqual(
    constraints(SPEC, {
      anyOf: [{ type: 'integer', minimum: 0, maximum: 10, enum: [1, 2] }, { type: 'null' }],
    }),
    { enum: [1, 2], maximum: 10, minimum: 0 },
  );
  assert.deepEqual(constraints(SPEC, { anyOf: [{ type: 'string' }], enum: ['x'] }), { enum: ['x'] });
  assert.deepEqual(constraints(SPEC, { type: 'boolean' }), {});
});
