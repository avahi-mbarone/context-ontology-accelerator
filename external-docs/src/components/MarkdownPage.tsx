// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { useEffect, useRef, useState, useCallback } from 'react'
import Markdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { pages, type PageId } from '../pages'

// Map .md filenames to hash route page IDs
const mdFileToPageId: Record<string, PageId> = {
  'deploying.md': 'deploying',
  'namespaces.md': 'namespaces',
  'authentication-setup.md': 'authentication-setup',
  'role-permission-management.md': 'role-permissions',
  'agent-access.md': 'agent-access',
  'cedar-policy-authoring.md': 'cedar-policies',
  'sources.md': 'sources',
  'index.md': 'sources',
  'cross-account-sources.md': 'cross-account-sources',
  'ontologies.md': 'ontologies',
  'metrics.md': 'metrics',
  'serve.md': 'serve',
  'getting-started.md': 'getting-started',
  'package-guide.md': 'package-guide',
  'smithy-codegen.md': 'smithy-codegen'
}

// Load mermaid lazily to avoid blocking initial render
let mermaidPromise: Promise<typeof import('mermaid')> | null = null
function getMermaid() {
  if (!mermaidPromise) {
    mermaidPromise = import('mermaid').then((mod) => {
      mod.default.initialize({
        startOnLoad: false,
        theme: 'default',
        securityLevel: 'strict',
      })
      return mod
    })
  }
  return mermaidPromise!
}

interface MarkdownPageProps {
  content: string
}

// Convert MkDocs admonition syntax to blockquotes that react-markdown renders
// !!! type "title"\n    content  →  > **Type: title**\n> content
function preprocessAdmonitions(md: string): string {
  return md.replace(
    /^!!! (\w+)(?: "([^"]*)")?\s*\n((?:    .+\n?)*)/gm,
    (_match, type: string, title: string | undefined, body: string) => {
      const label = type.charAt(0).toUpperCase() + type.slice(1)
      const heading = title ? `**${label}: ${title}**` : `**${label}**`
      const lines = body
        .split('\n')
        .map((line) => `> ${line.replace(/^    /, '')}`)
        .join('\n')
      return `> ${heading}\n>\n${lines}`
    },
  )
}

function Mermaid({ chart }: { chart: string }): React.JSX.Element {
  const containerRef = useRef<HTMLDivElement>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const el = containerRef.current
    if (!el) return

    let cancelled = false
    const id = `mermaid-${Math.random().toString(36).slice(2, 9)}`

    getMermaid()
      .then((mod) => mod.default.render(id, chart))
      .then(({ svg }) => {
        if (!cancelled && el) {
          // SVG is from mermaid.render() with our own committed markdown as input.
          // No user-supplied content reaches here, so innerHTML is safe.
          el.innerHTML = svg
        }
      })
      .catch(() => {
        if (!cancelled) setError(chart)
      })

    return () => {
      cancelled = true
    }
  }, [chart])

  if (error) {
    return <pre className="text-sm bg-gray-100 p-4 rounded overflow-x-auto"><code>{error}</code></pre>
  }
  return <div ref={containerRef} className="mermaid-diagram my-4 flex justify-center [&_svg]:max-w-full" />
}

function resolveHref(href: string): string {
  const filename = href.split('/').pop()?.split('#')[0] ?? href
  const pageId = mdFileToPageId[filename]
  if (pageId && pageId in pages) {
    return `#/${pageId}`
  }
  return href
}

export function MarkdownPage({ content }: MarkdownPageProps): React.JSX.Element {
  const renderCode = useCallback(
    (props: { className?: string; children?: React.ReactNode }) => {
      const match = /language-mermaid/.exec(props.className ?? '')
      if (match) {
        const chart = String(props.children).replace(/\n$/, '')
        return <Mermaid chart={chart} />
      }
      return <code className={props.className}>{props.children}</code>
    },
    [],
  )

  const renderLink = useCallback(
    (props: { href?: string; children?: React.ReactNode }) => {
      const href = props.href ?? ''
      if (href.endsWith('.md') || href.includes('.md#') || href.includes('.md)')) {
        const resolved = resolveHref(href)
        return <a href={resolved}>{props.children}</a>
      }
      return (
        <a href={href} target="_blank" rel="noopener noreferrer">
          {props.children}
        </a>
      )
    },
    [],
  )

  return (
    <article className="prose max-w-none">
      <Markdown
        remarkPlugins={[remarkGfm]}
        components={{
          code: renderCode,
          a: renderLink,
        }}
      >
        {preprocessAdmonitions(content)}
      </Markdown>
    </article>
  )
}
