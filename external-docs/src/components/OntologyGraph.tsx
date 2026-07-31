// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

type Tier = 'hub' | 'secondary' | 'leaf'

type NodeShape = {
  id: string
  label: string
  kind: string
  x: number
  y: number
  emphasis?: boolean
  tier?: Tier
  showIn?: 'hero' | 'band' | 'both'
}

type EdgeShape = {
  from: string
  to: string
  label?: string
  dashed?: boolean
  curve?: number // quadratic bezier control offset, perpendicular to the segment
  showIn?: 'hero' | 'band' | 'both'
  strength?: 'primary' | 'secondary'
}

const NODES: NodeShape[] = [
  // ----- Hubs -----
  { id: 'policy', label: 'Policy', kind: 'owl:Class', x: 320, y: 180, tier: 'hub' },
  { id: 'claim', label: 'Claim', kind: 'owl:Class', x: 560, y: 320, emphasis: true, tier: 'hub' },
  { id: 'party', label: 'Party', kind: 'owl:Class', x: 150, y: 360, tier: 'hub' },

  // ----- Secondary classes -----
  { id: 'coverage', label: 'Coverage', kind: 'owl:Class', x: 470, y: 90, tier: 'secondary' },
  { id: 'payment', label: 'Payment', kind: 'owl:Class', x: 810, y: 280, tier: 'secondary' },
  { id: 'invoice', label: 'Invoice', kind: 'owl:Class', x: 750, y: 460, tier: 'secondary' },
  { id: 'adjuster', label: 'Adjuster', kind: 'owl:Class', x: 380, y: 470, tier: 'secondary' },

  // Extra secondaries — hero only, for visual richness behind the copy
  { id: 'endorsement', label: 'Endorsement', kind: 'owl:Class', x: 700, y: 130, tier: 'secondary', showIn: 'hero' },
  { id: 'peril', label: 'Peril', kind: 'owl:Class', x: 220, y: 210, tier: 'secondary', showIn: 'hero' },
  { id: 'document', label: 'Document', kind: 'owl:Class', x: 80, y: 200, tier: 'secondary', showIn: 'hero' },
  { id: 'premium', label: 'Premium', kind: 'owl:Class', x: 590, y: 510, tier: 'secondary', showIn: 'hero' },

  // ----- Leaf dots (instances / satellite concepts) — hero only -----
  { id: 'l-pol-1', label: '', kind: '', x: 270, y: 140, tier: 'leaf', showIn: 'hero' },
  { id: 'l-pol-2', label: '', kind: '', x: 370, y: 230, tier: 'leaf', showIn: 'hero' },
  { id: 'l-clm-1', label: '', kind: '', x: 610, y: 280, tier: 'leaf', showIn: 'hero' },
  { id: 'l-clm-2', label: '', kind: '', x: 540, y: 380, tier: 'leaf', showIn: 'hero' },
  { id: 'l-clm-3', label: '', kind: '', x: 500, y: 285, tier: 'leaf', showIn: 'hero' },
  { id: 'l-par-1', label: '', kind: '', x: 110, y: 320, tier: 'leaf', showIn: 'hero' },
  { id: 'l-par-2', label: '', kind: '', x: 190, y: 420, tier: 'leaf', showIn: 'hero' },
  { id: 'l-pay-1', label: '', kind: '', x: 855, y: 240, tier: 'leaf', showIn: 'hero' },
  { id: 'l-cov-1', label: '', kind: '', x: 430, y: 60, tier: 'leaf', showIn: 'hero' },
  { id: 'l-adj-1', label: '', kind: '', x: 320, y: 440, tier: 'leaf', showIn: 'hero' },
]

const EDGES: EdgeShape[] = [
  { from: 'policy', to: 'claim', label: 'hasClaim', strength: 'primary' },
  { from: 'policy', to: 'coverage', label: 'includes' },
  { from: 'party', to: 'policy', label: 'holds', strength: 'primary' },
  { from: 'claim', to: 'payment', label: 'resolvedBy', strength: 'primary' },
  { from: 'claim', to: 'invoice', label: 'generates' },
  { from: 'claim', to: 'adjuster', label: 'assignedTo' },
  { from: 'party', to: 'claim', label: 'files', dashed: true, curve: -110 },
  { from: 'coverage', to: 'claim', label: 'governs', dashed: true },

  // Hero-only extras for richness
  { from: 'coverage', to: 'endorsement', showIn: 'hero' },
  { from: 'policy', to: 'peril', showIn: 'hero' },
  { from: 'party', to: 'document', showIn: 'hero' },
  { from: 'payment', to: 'invoice', showIn: 'hero' },
  { from: 'adjuster', to: 'party', showIn: 'hero', curve: 140 },
  { from: 'claim', to: 'premium', showIn: 'hero' },
  { from: 'policy', to: 'premium', showIn: 'hero', dashed: true, curve: 90 },
  { from: 'endorsement', to: 'policy', showIn: 'hero', curve: -60 },
  { from: 'peril', to: 'claim', showIn: 'hero', dashed: true, curve: 70 },
]

function nodeById(id: string): NodeShape {
  const node = NODES.find((candidate) => candidate.id === id)
  if (!node) {
    throw new Error(`Unknown node id: ${id}`)
  }
  return node
}

function bezierPath(ax: number, ay: number, bx: number, by: number, curve: number): string {
  const mx = (ax + bx) / 2
  const my = (ay + by) / 2
  const dx = bx - ax
  const dy = by - ay
  const len = Math.hypot(dx, dy) || 1
  // Perpendicular unit vector
  const nx = -dy / len
  const ny = dx / len
  const cx = mx + nx * curve
  const cy = my + ny * curve
  return `M ${ax} ${ay} Q ${cx} ${cy} ${bx} ${by}`
}

type Props = {
  variant?: 'hero' | 'band'
}

export function OntologyGraph({ variant = 'hero' }: Props): React.JSX.Element {
  const width = 900
  const height = 560
  const isHero = variant === 'hero'

  const visibleNodes = NODES.filter((n) => n.showIn === undefined || n.showIn === 'both' || n.showIn === variant)
  const visibleEdges = EDGES.filter((e) => e.showIn === undefined || e.showIn === 'both' || e.showIn === variant)

  return (
    <svg
      viewBox={`0 0 ${width} ${height}`}
      xmlns="http://www.w3.org/2000/svg"
      aria-hidden="true"
      className="h-full w-full"
      preserveAspectRatio="xMidYMid meet"
    >
      <defs>
        <radialGradient id="claim-halo" cx="50%" cy="50%" r="50%">
          <stop offset="0%" stopColor="#b5462a" stopOpacity="0.22" />
          <stop offset="55%" stopColor="#b5462a" stopOpacity="0.06" />
          <stop offset="100%" stopColor="#b5462a" stopOpacity="0" />
        </radialGradient>
      </defs>

      {/* Edges */}
      <g className="text-[#1a1915]">
        {visibleEdges.map((edge) => {
          const a = nodeById(edge.from)
          const b = nodeById(edge.to)
          const primary = edge.strength === 'primary'
          const opacity = isHero ? (primary ? 0.16 : 0.1) : (primary ? 0.6 : 0.45)
          const stroke = isHero ? (primary ? 0.9 : 0.6) : 1.2
          const dash = edge.dashed ? (isHero ? '2 6' : '3 6') : undefined
          const flowClass = edge.dashed && !isHero ? 'edge-flow' : undefined

          if (edge.curve) {
            return (
              <path
                key={`${edge.from}-${edge.to}`}
                d={bezierPath(a.x, a.y, b.x, b.y, edge.curve)}
                stroke="currentColor"
                strokeOpacity={opacity}
                strokeWidth={stroke}
                strokeDasharray={dash}
                fill="none"
                className={flowClass}
              />
            )
          }

          return (
            <line
              key={`${edge.from}-${edge.to}`}
              x1={a.x}
              y1={a.y}
              x2={b.x}
              y2={b.y}
              stroke="currentColor"
              strokeOpacity={opacity}
              strokeWidth={stroke}
              strokeDasharray={dash}
              className={flowClass}
            />
          )
        })}
      </g>

      {/* Edge labels — only on the detailed band variant */}
      {!isHero && (
        <g className="text-[#3a3731]" style={{ opacity: 0.7 }}>
          {visibleEdges.map((edge) => {
            const a = nodeById(edge.from)
            const b = nodeById(edge.to)
            const mx = (a.x + b.x) / 2
            const my = (a.y + b.y) / 2
            if (!edge.label) return null
            return (
              <text
                key={`lbl-${edge.from}-${edge.to}`}
                x={mx}
                y={my - 4}
                fontSize={10}
                textAnchor="middle"
                fontFamily="var(--font-mono)"
                fill="currentColor"
                letterSpacing="0.02em"
              >
                {edge.label}
              </text>
            )
          })}
        </g>
      )}

      {/* Claim halo — only on the detailed band variant */}
      {!isHero && (
        <circle cx={nodeById('claim').x} cy={nodeById('claim').y} r={90} fill="url(#claim-halo)" />
      )}

      {/* Very faint depth wash behind the main hub in hero mode */}
      {isHero && (
        <circle
          cx={nodeById('claim').x}
          cy={nodeById('claim').y}
          r={160}
          fill="#1a1915"
          fillOpacity={0.035}
        />
      )}

      {/* Nodes */}
      <g>
        {visibleNodes.map((node) => {
          const isEmphasis = node.emphasis === true
          const tier: Tier = node.tier ?? 'secondary'

          if (isHero && tier === 'leaf') {
            return (
              <circle
                key={node.id}
                cx={node.x}
                cy={node.y}
                r={1.8}
                fill="#1a1915"
                opacity={0.22}
              />
            )
          }

          if (isHero && tier === 'hub') {
            return (
              <g key={node.id}>
                <circle cx={node.x} cy={node.y} r={22} fill="none" stroke="#1a1915" strokeOpacity={0.06} strokeWidth={0.75} />
                <circle cx={node.x} cy={node.y} r={12} fill="none" stroke="#1a1915" strokeOpacity={0.16} strokeWidth={0.75} />
                <circle cx={node.x} cy={node.y} r={3.8} fill="#1a1915" opacity={0.4} />
                <text
                  x={node.x + 16}
                  y={node.y + 4}
                  fontSize={14}
                  fontFamily="var(--font-display)"
                  fontStyle="italic"
                  fontWeight={500}
                  fill="#1a1915"
                  fillOpacity={0.32}
                  letterSpacing="0.01em"
                >
                  {node.label}
                </text>
              </g>
            )
          }

          if (isHero) {
            // secondary
            return (
              <g key={node.id}>
                <circle cx={node.x} cy={node.y} r={8} fill="none" stroke="#1a1915" strokeOpacity={0.14} strokeWidth={0.7} />
                <circle cx={node.x} cy={node.y} r={2.2} fill="#1a1915" opacity={0.28} />
                <text
                  x={node.x + 13}
                  y={node.y + 3.5}
                  fontSize={11.5}
                  fontFamily="var(--font-display)"
                  fontStyle="italic"
                  fontWeight={400}
                  fill="#1a1915"
                  fillOpacity={0.22}
                  letterSpacing="0.01em"
                >
                  {node.label}
                </text>
              </g>
            )
          }

          // band variant — keep original detailed rendering
          return (
            <g
              key={node.id}
              className={isEmphasis ? 'claim-pulse' : undefined}
              style={{ transformOrigin: `${node.x}px ${node.y}px` }}
            >
              <circle
                cx={node.x}
                cy={node.y}
                r={isEmphasis ? 7 : 4.5}
                fill={isEmphasis ? '#b5462a' : '#1a1915'}
                opacity={isEmphasis ? 1 : 0.82}
              />
              <circle
                cx={node.x}
                cy={node.y}
                r={isEmphasis ? 14 : 9}
                fill="none"
                stroke={isEmphasis ? '#b5462a' : '#1a1915'}
                strokeOpacity={isEmphasis ? 0.35 : 0.22}
                strokeWidth={1}
              />
              <text
                x={node.x + 16}
                y={node.y + 5}
                fontSize={15}
                fontFamily="var(--font-display)"
                fontWeight={isEmphasis ? 600 : 500}
                fill={isEmphasis ? '#8a3420' : '#1a1915'}
                fillOpacity={isEmphasis ? 1 : 0.78}
              >
                {node.label}
              </text>
              {node.kind && (
                <text
                  x={node.x + 16}
                  y={node.y + 20}
                  fontSize={9}
                  fontFamily="var(--font-mono)"
                  fill="#6b675d"
                  fillOpacity={0.68}
                  letterSpacing="0.06em"
                >
                  {node.kind}
                </text>
              )}
            </g>
          )
        })}
      </g>
    </svg>
  )
}
