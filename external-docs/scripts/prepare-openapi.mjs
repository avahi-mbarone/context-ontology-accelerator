// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

// Copies the generated OpenAPI specs into public/api/ for the Scalar API
// reference, injecting a `servers` block (the generated specs ship without
// one). Run from external-docs/ by the Pages CI job and locally before
// `pnpm dev`/`pnpm build`.
import { readFileSync, writeFileSync, mkdirSync } from 'node:fs'
import { resolve, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

const here = dirname(fileURLToPath(import.meta.url))
const repoRoot = resolve(here, '../..')
const genDir = resolve(repoRoot, 'smithy-generated/openapi/openapi')
// Full Smithy model AST — carries per-enum-value documentation that the OpenAPI
// conversion drops (OpenAPI represents an enum as a bare string array). We read
// it back to re-attach value docs as an x-enumDescriptions extension.
const modelPath = resolve(repoRoot, 'smithy-generated/openapi/model/model.json')
const outDir = resolve(here, '../public/api')

// Placeholder used when no real endpoint is available (local dev, or a pipeline
// with no custom domain configured). Context Ontology Accelerator is self-deployed per
// customer, so there is no single canonical endpoint baked into the source.
export const PLACEHOLDER_BASE_URL = 'https://api.your-ontology-accelerator-deployment.example.com'

const SPECS = [
  { in: 'ControlPlaneService.openapi.json', out: 'control-plane.openapi.json' },
  { in: 'DataLayerService.openapi.json', out: 'data-layer.openapi.json' },
]

// Resolve the base URL for the `servers` block from the environment when the
// pipeline provides one, else fall back to the placeholder. Accepts either a
// full URL (https://…) or a bare hostname (the shape of CI's DEV_API_DOMAIN),
// which we normalise to https://. Only https (or http://localhost for dev) is
// accepted; anything else — or an unparseable value — falls back to the
// placeholder rather than emitting a bad server URL.
export function resolveBaseUrl(rawValue) {
  const raw = rawValue?.trim()
  if (!raw) return { url: PLACEHOLDER_BASE_URL, resolved: false }
  try {
    // A value carrying its own scheme must use http/https; anything else
    // (ftp://, javascript:, protocol-relative //host) is rejected. A bare
    // hostname (no scheme, no leading //) is normalised to https://.
    const hasScheme = /^[a-z][a-z0-9+.-]*:/i.test(raw)
    const isProtocolRelative = raw.startsWith('//')
    if (isProtocolRelative) throw new Error('protocol-relative URLs are not allowed')
    if (hasScheme && !/^https?:\/\//i.test(raw)) {
      throw new Error('only http(s) URLs are allowed')
    }
    const candidate = hasScheme ? raw : `https://${raw}`
    const parsed = new URL(candidate)
    const isLocalhost = parsed.hostname === 'localhost' || parsed.hostname === '127.0.0.1'
    if (parsed.protocol !== 'https:' && !(parsed.protocol === 'http:' && isLocalhost)) {
      throw new Error('only https:// (or http://localhost) is allowed')
    }
    // Preserve any path (e.g. a `/v1` stage) but drop a trailing slash so the
    // OpenAPI paths (which start with `/`) don't produce a double slash.
    const normalised = candidate.endsWith('/') ? candidate.slice(0, -1) : candidate
    return { url: normalised, resolved: true }
  } catch (err) {
    console.error(`Ignoring invalid SCL_API_BASE_URL "${raw}": ${err.message}`)
    return { url: PLACEHOLDER_BASE_URL, resolved: false }
  }
}

// Build the OpenAPI `servers` block. Expressed as a `{baseUrl}` server variable
// rather than a static URL: Scalar only renders an editable field for server
// *variables*, so this lets users point try-it-out at their own deployment. The
// default is the resolved endpoint when the pipeline supplies one, else the
// placeholder.
export function buildServers(baseUrl) {
  return [
    {
      url: '{baseUrl}',
      description: 'Your Context Ontology Accelerator API endpoint',
      variables: {
        baseUrl: {
          default: baseUrl,
          description: 'Base URL of your Context Ontology Accelerator deployment — edit to match your environment',
        },
      },
    },
  ]
}

// Build a map of { EnumSimpleName -> { wireValue -> description } } from the
// Smithy model AST. OpenAPI drops per-enum-value docs (an enum becomes a bare
// string array), so we recover them here to re-attach as x-enumDescriptions.
// Keyed by the enum value's WIRE value (smithy.api#enumValue), which is what
// appears in the OpenAPI `enum` array; falls back to the member name when a
// value has no explicit wire value.
export function buildEnumDescriptions(model) {
  const byEnum = {}
  for (const [shapeId, shape] of Object.entries(model.shapes ?? {})) {
    if (shape.type !== 'enum') continue
    const simpleName = shapeId.split('#').pop()
    const valueDocs = {}
    for (const [memberName, member] of Object.entries(shape.members ?? {})) {
      const traits = member.traits ?? {}
      const doc = traits['smithy.api#documentation']
      if (!doc) continue
      const wire = traits['smithy.api#enumValue'] ?? memberName
      valueDocs[wire] = doc
    }
    if (Object.keys(valueDocs).length > 0) byEnum[simpleName] = valueDocs
  }
  return byEnum
}

// Walk a spec's component schemas; for any enum schema, attach an
// x-enumDescriptions map (Scalar renders this per value). Only descriptions for
// values actually present in the schema's `enum` array are included. Mutates and
// returns the doc. Returns the number of enum schemas annotated.
export function injectEnumDescriptions(doc, enumDescriptions) {
  const schemas = doc.components?.schemas ?? {}
  let annotated = 0
  for (const [name, schema] of Object.entries(schemas)) {
    if (!Array.isArray(schema.enum)) continue
    const valueDocs = enumDescriptions[name]
    if (!valueDocs) continue
    const present = {}
    for (const value of schema.enum) {
      if (valueDocs[value] !== undefined) present[value] = valueDocs[value]
    }
    if (Object.keys(present).length > 0) {
      schema['x-enumDescriptions'] = present
      annotated += 1
    }
  }
  return annotated
}

// Read one generated spec, inject the servers block and enum value
// descriptions, then write it to the output dir. Returns the output path.
// Throws with a clear message on I/O or JSON error so the caller can fail the
// build loudly rather than emit a partial site.
export function prepareSpec(spec, servers, enumDescriptions = {}, dirs = { genDir, outDir }) {
  const srcPath = resolve(dirs.genDir, spec.in)
  let doc
  try {
    doc = JSON.parse(readFileSync(srcPath, 'utf8'))
  } catch (err) {
    throw new Error(`could not read/parse ${srcPath}: ${err.message}`)
  }
  doc.servers = servers
  injectEnumDescriptions(doc, enumDescriptions)
  const destPath = resolve(dirs.outDir, spec.out)
  try {
    writeFileSync(destPath, JSON.stringify(doc, null, 2))
  } catch (err) {
    throw new Error(`could not write ${destPath}: ${err.message}`)
  }
  return destPath
}

// Load the Smithy model AST and derive enum value descriptions. The model is a
// required generation artifact; if it is missing (e.g. a stale checkout) we warn
// and continue without enum docs rather than fail the docs build.
function loadEnumDescriptions() {
  let model
  try {
    model = JSON.parse(readFileSync(modelPath, 'utf8'))
  } catch (err) {
    console.warn(`No model AST at ${modelPath} (${err.message}); skipping enum value descriptions.`)
    return {}
  }
  return buildEnumDescriptions(model)
}

function main() {
  const { url: baseUrl, resolved } = resolveBaseUrl(process.env.SCL_API_BASE_URL)
  const servers = buildServers(baseUrl)
  const enumDescriptions = loadEnumDescriptions()

  console.log(
    resolved
      ? `API base URL from SCL_API_BASE_URL: ${baseUrl}`
      : `SCL_API_BASE_URL not set — using placeholder: ${baseUrl}`,
  )

  try {
    mkdirSync(outDir, { recursive: true })
  } catch (err) {
    console.error(`Failed to create output directory ${outDir}: ${err.message}`)
    process.exit(1)
  }

  for (const spec of SPECS) {
    try {
      prepareSpec(spec, servers, enumDescriptions)
      console.log(`prepared ${spec.out}`)
    } catch (err) {
      console.error(`Failed to prepare ${spec.out}: ${err.message}`)
      process.exit(1)
    }
  }
}

// Only run when invoked as a script, not when imported by the test module.
if (process.argv[1] && resolve(process.argv[1]) === resolve(fileURLToPath(import.meta.url))) {
  main()
}
