// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

// Unit tests for prepare-openapi.mjs. Uses Node's built-in test runner
// (`node --test`) so no extra dependency is added to the docs project.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { mkdtempSync, mkdirSync, writeFileSync, readFileSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { resolve, join } from 'node:path'

import {
  resolveBaseUrl,
  buildServers,
  prepareSpec,
  buildEnumDescriptions,
  injectEnumDescriptions,
  PLACEHOLDER_BASE_URL,
} from './prepare-openapi.mjs'

// ── resolveBaseUrl ────────────────────────────────────────────────────────────
test('resolveBaseUrl: missing value falls back to placeholder', () => {
  assert.deepEqual(resolveBaseUrl(undefined), { url: PLACEHOLDER_BASE_URL, resolved: false })
  assert.deepEqual(resolveBaseUrl(''), { url: PLACEHOLDER_BASE_URL, resolved: false })
  assert.deepEqual(resolveBaseUrl('   '), { url: PLACEHOLDER_BASE_URL, resolved: false })
})

test('resolveBaseUrl: bare hostname is normalised to https', () => {
  assert.deepEqual(resolveBaseUrl('api.ontology-accelerator.example.com'), {
    url: 'https://api.ontology-accelerator.example.com',
    resolved: true,
  })
})

test('resolveBaseUrl: full https URL is preserved, path kept', () => {
  assert.deepEqual(resolveBaseUrl('https://api.ontology-accelerator.example.com/v1'), {
    url: 'https://api.ontology-accelerator.example.com/v1',
    resolved: true,
  })
})

test('resolveBaseUrl: trailing slash is trimmed', () => {
  assert.deepEqual(resolveBaseUrl('https://api.ontology-accelerator.example.com/'), {
    url: 'https://api.ontology-accelerator.example.com',
    resolved: true,
  })
})

test('resolveBaseUrl: http://localhost is allowed for dev', () => {
  assert.deepEqual(resolveBaseUrl('http://localhost:8080'), {
    url: 'http://localhost:8080',
    resolved: true,
  })
})

test('resolveBaseUrl: http://127.0.0.1 is allowed for dev', () => {
  assert.deepEqual(resolveBaseUrl('http://127.0.0.1:8080'), {
    url: 'http://127.0.0.1:8080',
    resolved: true,
  })
})

test('resolveBaseUrl: mixed-case disallowed scheme is rejected -> placeholder', () => {
  assert.deepEqual(resolveBaseUrl('FtP://api.example.com'), {
    url: PLACEHOLDER_BASE_URL,
    resolved: false,
  })
})

test('resolveBaseUrl: mixed-case https scheme is accepted', () => {
  assert.deepEqual(resolveBaseUrl('HtTpS://api.example.com'), {
    url: 'HtTpS://api.example.com',
    resolved: true,
  })
})

test('resolveBaseUrl: non-localhost http is rejected -> placeholder', () => {
  assert.deepEqual(resolveBaseUrl('http://api.insecure.example.com'), {
    url: PLACEHOLDER_BASE_URL,
    resolved: false,
  })
})

test('resolveBaseUrl: non-http(s) scheme is rejected -> placeholder', () => {
  // An explicit disallowed scheme like ftp:// or javascript: must fall back
  // rather than being wrapped into a malformed https://ftp://… value.
  assert.deepEqual(resolveBaseUrl('ftp://api.example.com'), {
    url: PLACEHOLDER_BASE_URL,
    resolved: false,
  })
  assert.deepEqual(resolveBaseUrl('javascript:alert(1)'), {
    url: PLACEHOLDER_BASE_URL,
    resolved: false,
  })
})

test('resolveBaseUrl: protocol-relative URL is rejected -> placeholder', () => {
  assert.deepEqual(resolveBaseUrl('//evil.example.com'), {
    url: PLACEHOLDER_BASE_URL,
    resolved: false,
  })
})

// ── buildServers ──────────────────────────────────────────────────────────────
test('buildServers: emits an editable {baseUrl} variable with the given default', () => {
  const servers = buildServers('https://api.example.com')
  assert.equal(servers.length, 1)
  assert.equal(servers[0].url, '{baseUrl}')
  assert.equal(servers[0].variables.baseUrl.default, 'https://api.example.com')
})

// ── prepareSpec ───────────────────────────────────────────────────────────────
test('prepareSpec: injects servers block and writes valid JSON', () => {
  const dir = mkdtempSync(join(tmpdir(), 'prep-openapi-'))
  try {
    const gen = join(dir, 'gen')
    const out = join(dir, 'out')
    mkdirSync(gen, { recursive: true })
    mkdirSync(out, { recursive: true })
    writeFileSync(join(gen, 'In.json'), JSON.stringify({ openapi: '3.0.2', paths: {} }))

    const servers = buildServers('https://api.example.com')
    const destPath = prepareSpec({ in: 'In.json', out: 'Out.json' }, servers, {}, {
      genDir: gen,
      outDir: out,
    })

    const written = JSON.parse(readFileSync(destPath, 'utf8'))
    assert.deepEqual(written.servers, servers)
    assert.equal(written.openapi, '3.0.2')
  } finally {
    rmSync(dir, { recursive: true, force: true })
  }
})

test('prepareSpec: throws a clear error when the source spec is missing', () => {
  const dir = mkdtempSync(join(tmpdir(), 'prep-openapi-'))
  try {
    assert.throws(
      () => prepareSpec({ in: 'Nope.json', out: 'Out.json' }, buildServers('https://x.example.com'), {}, {
        genDir: dir,
        outDir: dir,
      }),
      /could not read\/parse/,
    )
  } finally {
    rmSync(dir, { recursive: true, force: true })
  }
})

test('prepareSpec: throws a clear error when the source spec is malformed JSON', () => {
  const dir = mkdtempSync(join(tmpdir(), 'prep-openapi-'))
  try {
    writeFileSync(join(dir, 'Bad.json'), '{ not valid json')
    assert.throws(
      () => prepareSpec({ in: 'Bad.json', out: 'Out.json' }, buildServers('https://x.example.com'), {}, {
        genDir: dir,
        outDir: dir,
      }),
      /could not read\/parse/,
    )
  } finally {
    rmSync(dir, { recursive: true, force: true })
  }
})

test('prepareSpec: throws a clear error when the destination cannot be written', () => {
  const dir = mkdtempSync(join(tmpdir(), 'prep-openapi-'))
  try {
    writeFileSync(join(dir, 'In.json'), JSON.stringify({ openapi: '3.0.2', paths: {} }))
    // Create a plain file where the output DIRECTORY is expected, so resolving
    // a child path under it and writing fails (ENOTDIR).
    const outAsFile = join(dir, 'not-a-dir')
    writeFileSync(outAsFile, 'x')
    assert.throws(
      () => prepareSpec({ in: 'In.json', out: 'Out.json' }, buildServers('https://x.example.com'), {}, {
        genDir: dir,
        outDir: outAsFile,
      }),
      /could not write/,
    )
  } finally {
    rmSync(dir, { recursive: true, force: true })
  }
})

// ── buildEnumDescriptions ─────────────────────────────────────────────────────
const SAMPLE_MODEL = {
  shapes: {
    'com.example#PrincipalType': {
      type: 'enum',
      members: {
        USER: { traits: { 'smithy.api#enumValue': 'User', 'smithy.api#documentation': 'An individual user.' } },
        GROUP: { traits: { 'smithy.api#enumValue': 'Group', 'smithy.api#documentation': 'A group of users.' } },
      },
    },
    'com.example#Plain': {
      type: 'enum',
      // No explicit enumValue → key falls back to the member name.
      members: {
        ACTIVE: { traits: { 'smithy.api#documentation': 'It is active.' } },
        UNDOC: { traits: {} },
      },
    },
    'com.example#NotAnEnum': { type: 'structure', members: {} },
  },
}

test('buildEnumDescriptions: keys by wire value and skips undocumented values', () => {
  const result = buildEnumDescriptions(SAMPLE_MODEL)
  assert.deepEqual(result.PrincipalType, {
    User: 'An individual user.',
    Group: 'A group of users.',
  })
  // member-name fallback when no enumValue, and undocumented member omitted
  assert.deepEqual(result.Plain, { ACTIVE: 'It is active.' })
  assert.equal('NotAnEnum' in result, false)
})

test('buildEnumDescriptions: tolerates a model with no shapes', () => {
  assert.deepEqual(buildEnumDescriptions({}), {})
})

// ── injectEnumDescriptions ────────────────────────────────────────────────────
test('injectEnumDescriptions: attaches x-enumDescriptions for matching enum values only', () => {
  const doc = {
    components: {
      schemas: {
        PrincipalType: { type: 'string', enum: ['User', 'Group'] },
        NotEnum: { type: 'object', properties: {} },
      },
    },
  }
  const enumDescriptions = { PrincipalType: { User: 'An individual user.', Group: 'A group.', Ghost: 'not in enum' } }
  const count = injectEnumDescriptions(doc, enumDescriptions)
  assert.equal(count, 1)
  // Only values present in the enum array are included; "Ghost" is dropped.
  assert.deepEqual(doc.components.schemas.PrincipalType['x-enumDescriptions'], {
    User: 'An individual user.',
    Group: 'A group.',
  })
  assert.equal('x-enumDescriptions' in doc.components.schemas.NotEnum, false)
})

test('injectEnumDescriptions: no-op when the enum has no descriptions', () => {
  const doc = { components: { schemas: { Foo: { type: 'string', enum: ['A'] } } } }
  const count = injectEnumDescriptions(doc, {})
  assert.equal(count, 0)
  assert.equal('x-enumDescriptions' in doc.components.schemas.Foo, false)
})

test('injectEnumDescriptions: tolerates a spec with no components', () => {
  assert.equal(injectEnumDescriptions({}, { X: { A: 'a' } }), 0)
})
