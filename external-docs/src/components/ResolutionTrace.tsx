// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { useEffect, useRef, useState } from 'react'

type TierState = 'skipped' | 'resolved' | 'not-reached' | 'denied'

type TierFact = {
  label: string
  value: string
  tone?: 'default' | 'positive' | 'warning'
}

type TierRow = {
  index: number
  name: string
  state: TierState
  detail?: string
  /** Optional code-ish snippet that expands in the focus panel when revealed. */
  snippet?: { lang: string; body: string }
  /** Optional labeled facts (policy, latency, etc.) shown below the snippet. */
  facts?: TierFact[]
}

type AnswerGrid = {
  kind: 'grid'
  rows: { label: string; value: string }[]
  provenance: string
}

type AnswerSingle = {
  kind: 'single'
  value: string
  label: string
  provenance: string
}

type AnswerDenied = {
  kind: 'denied'
  reason: string
  policy: string
}

type AnswerNarrative = {
  kind: 'narrative'
  headline: string
  body: string
  provenance: string
}

type Answer = AnswerGrid | AnswerSingle | AnswerDenied | AnswerNarrative

type Scenario = {
  id: string
  actor: string
  prompt: string
  /**
   * Exact substrings of `prompt` that should be softly highlighted, each
   * authored against the tier that actually bound it. The pale wash fades
   * in when `phase >= tier`, so the reader sees each term light up the
   * instant its tier resolves — prompt becomes a live map of what got
   * bound at each step.
   */
  highlights?: { text: string; tier: 1 | 2 | 3 }[]
  tiers: TierRow[]
  answer: Answer
  outcome: {
    label: string
    tone: 'positive' | 'warning'
  }
}

const SCENARIOS: Scenario[] = [
  {
    id: 'solvency',
    actor: 'risk-analyst · regulatory-agent',
    prompt:
      '“Give me the Solvency II ratio for in-force commercial property policies as of last quarter-end, excluding cat-exposed lines.”',
    highlights: [
      { text: 'Solvency II ratio', tier: 1 },
      { text: 'commercial property', tier: 1 },
      { text: 'cat-exposed', tier: 1 },
    ],
    tiers: [
      {
        index: 1,
        name: 'Governed metric',
        state: 'resolved',
        detail: 'solvency_ii_ratio · 0 LLM · 14 ms',
        snippet: {
          lang: 'metric · solvency_ii_ratio',
          body: 'SELECT eligible_own_funds / scr AS ratio\nFROM quarterly_capital\nWHERE line_of_business IN (:policy.commercial_property)\n  AND reporting_date = :period.q_end\n  AND excluded_flags ⊇ {:cat_exposed}',
        },
        facts: [
          { label: 'source', value: 'DynamoDB · pre-compiled' },
          { label: 'ontology', value: 'ReportingPeriod · LineOfBusiness' },
          { label: 'llm', value: '0 calls' },
          { label: 'latency', value: '14 ms' },
        ],
      },
      { index: 2, name: 'SPARQL over VKG', state: 'not-reached', detail: 'not reached' },
      { index: 3, name: 'Agentic fallback', state: 'not-reached', detail: 'not reached' },
    ],
    answer: {
      kind: 'single',
      value: '187.4%',
      label: 'Solvency II · commercial property · Q ending 2026-03-31',
      provenance: 'quarterly_capital.v4 · deterministic',
    },
    outcome: { label: 'resolved', tone: 'positive' },
  },
  {
    id: 'exposure',
    actor: 'portfolio-agent · actuarial',
    prompt:
      '“Net exposure by reinsurance cohort on policies with open catastrophe claims above the deductible, reconciled to yesterday’s ceded-risk report.”',
    highlights: [
      { text: 'reinsurance cohort', tier: 2 },
      { text: 'catastrophe claims', tier: 2 },
      { text: 'ceded-risk report', tier: 2 },
    ],
    tiers: [
      {
        index: 1,
        name: 'Governed metric',
        state: 'skipped',
        detail: 'no metric for cross-cohort decomposition',
      },
      {
        index: 2,
        name: 'SPARQL over VKG',
        state: 'resolved',
        detail: '4 classes · 3 sources · cedar.allow · 412 ms',
        snippet: {
          lang: 'sparql',
          body: 'SELECT ?cohort (SUM(?gross - ?ceded) AS ?net)\nWHERE {\n  ?p a :Policy ; :reinsuranceCohort ?cohort ;\n     :hasClaim [ a :CatastropheClaim ;\n                 :status "open" ; :amount ?gross ] ;\n     :cededPortion ?ceded .\n  FILTER(?gross > ?p/:deductible)\n} GROUP BY ?cohort',
        },
        facts: [
          { label: 'classes', value: 'Policy · CatClaim · Cohort' },
          { label: 'cedar', value: 'allow · actuarial-read', tone: 'positive' },
          { label: 'federation', value: 'Policy · Claims · Re-ledger' },
          { label: 'shacl', value: '0 violations' },
          { label: 'latency', value: '412 ms' },
        ],
      },
      { index: 3, name: 'Agentic fallback', state: 'not-reached', detail: 'not reached' },
    ],
    answer: {
      kind: 'grid',
      provenance: 'reconciled to ceded_report · 2026-04-28',
      rows: [
        { label: 'Treaty A · 2025', value: '$184M' },
        { label: 'Treaty B · 2025', value: '$91M' },
        { label: 'Facultative', value: '$47M' },
        { label: 'Retained', value: '$22M' },
      ],
    },
    outcome: { label: 'resolved', tone: 'positive' },
  },
  {
    id: 'agentic',
    actor: 'claims-copilot · adjuster-assist',
    prompt:
      '“Why is Claim-48217 still open after 90 days, and what does the adjuster notebook say about possible coverage ambiguity on the endorsement?”',
    highlights: [
      { text: 'Claim-48217', tier: 3 },
      { text: 'adjuster notebook', tier: 3 },
      { text: 'coverage ambiguity', tier: 3 },
    ],
    tiers: [
      {
        index: 1,
        name: 'Governed metric',
        state: 'skipped',
        detail: 'narrative synthesis, not a metric',
      },
      {
        index: 2,
        name: 'SPARQL over VKG',
        state: 'skipped',
        detail: 'partial; unstructured context required',
      },
      {
        index: 3,
        name: 'Agentic fallback',
        state: 'resolved',
        detail: 'composed from 3 sources by Context Manager',
        snippet: {
          lang: 'context manager · composed',
          body: 'VKG      → Claim-48217 · status=open · aging=94d · adjuster=A.Chen\nVector   → 2 notebook chunks · policy wording PDF (p.14)\nGraph DB → 4 related Claims under same endorsement',
        },
        facts: [
          { label: 'structured', value: 'Claim · Endorsement · Adjuster' },
          { label: 'unstructured', value: 'notebook · policy wording' },
          { label: 'cedar', value: 'allow · pii redacted', tone: 'positive' },
          { label: 'llm', value: '3 calls · 1.8 s' },
        ],
      },
    ],
    answer: {
      kind: 'narrative',
      headline: 'Coverage ambiguity on Endorsement E-214',
      body:
        'Adjuster flagged conflicting language between the endorsement (p.14) and the declarations page. 4 prior claims under the same endorsement have been escalated; legal review pending.',
      provenance: '2 docs · 1 graph path · redacted',
    },
    outcome: { label: 'resolved', tone: 'positive' },
  },
  {
    id: 'deny',
    actor: 'broker-portal · broker-12847',
    prompt:
      '“Show renewal pipeline and loss ratios for commercial auto accounts bound in the Northeast territory last month, including accounts outside my book.”',
    highlights: [
      { text: 'commercial auto', tier: 2 },
      { text: 'Northeast territory', tier: 2 },
      { text: 'outside my book', tier: 2 },
    ],
    tiers: [
      {
        index: 1,
        name: 'Governed metric',
        state: 'skipped',
        detail: 'no matching metric definition',
      },
      {
        index: 2,
        name: 'SPARQL over VKG',
        state: 'denied',
        detail: 'cedar.deny · broker_partition · 142 accounts filtered',
        snippet: {
          lang: 'sparql · halted',
          body: 'SELECT ?account ?premium ?lossRatio\nWHERE { ?a a :Account ;\n           :lineOfBusiness "commercial_auto" ;\n           :territory "northeast" ;\n           :boundMonth "2026-03" }',
        },
        facts: [
          { label: 'cedar', value: 'deny · broker_partition', tone: 'warning' },
          { label: 'reason', value: 'broker_id ≠ broker_of_record' },
          { label: 'scope', value: '0 rows · 142 filtered' },
          { label: 'action', value: 'halted pre-execution' },
        ],
      },
      { index: 3, name: 'Agentic fallback', state: 'not-reached', detail: 'not reached' },
    ],
    answer: {
      kind: 'denied',
      policy: 'broker_partition · namespace:underwriting',
      reason:
        'Broker accounts are partitioned by broker_of_record. Request spanned 142 accounts outside the caller’s book. Cedar denied authorization before SPARQL could execute; event logged.',
    },
    outcome: { label: 'blocked', tone: 'warning' },
  },
]

// Phase model:
//   0 = typing prompt
//   1 = Tier 1 evaluated
//   2 = Tier 2 evaluated
//   3 = Tier 3 evaluated
//   4 = answer revealed
type Phase = 0 | 1 | 2 | 3 | 4

const TYPE_INTERVAL_MS = 26
const POST_TYPE_PAUSE_MS = 450
const TIER_GAP_MS = 820
const ANSWER_GAP_MS = 520
const DWELL_MS = 6000
const EXIT_MS = 520

export function ResolutionTrace(): React.JSX.Element {
  const [scenarioIdx, setScenarioIdx] = useState(0)
  return (
    <div className="relative">
      {/* Soft halo behind the card */}
      <div
        aria-hidden="true"
        className="absolute -inset-10 rounded-[36px] bg-gradient-to-br from-terracotta/[0.06] via-transparent to-ink/[0.04] blur-3xl"
      />
      <div className="relative h-[612px] overflow-hidden rounded-2xl border border-ink/10 bg-paper shadow-[0_50px_100px_-50px_rgba(26,25,21,0.35)]">
        {/*
          Re-mount the entire scene when scenarioIdx changes. This guarantees a
          clean reset of every transition, avoids stale opacity fades on the
          new scenario, and keeps the typewriter honest.
        */}
        <ScenarioScene
          key={scenarioIdx}
          scenarioIdx={scenarioIdx}
          scenarioCount={SCENARIOS.length}
          onAdvance={() =>
            setScenarioIdx((i) => (i + 1) % SCENARIOS.length)
          }
        />
      </div>
    </div>
  )
}

function ScenarioScene({
  scenarioIdx,
  scenarioCount,
  onAdvance,
}: {
  scenarioIdx: number
  scenarioCount: number
  onAdvance: () => void
}): React.JSX.Element {
  const scenario = SCENARIOS[scenarioIdx]!
  const prompt = scenario.prompt

  const [phase, setPhase] = useState<Phase>(0)
  const [typed, setTyped] = useState(0)
  const [exiting, setExiting] = useState(false)
  const tierListRef = useRef<HTMLOListElement | null>(null)

  // Auto-scroll the tier list so the most-recently-revealed tier is in view.
  // Waits a frame so the newly-revealed content (detail + possible expansion)
  // has laid out before measuring scroll height.
  useEffect(() => {
    if (phase === 0) return
    const el = tierListRef.current
    if (!el) return
    const raf = requestAnimationFrame(() => {
      el.scrollTo({ top: el.scrollHeight, behavior: 'smooth' })
    })
    return () => cancelAnimationFrame(raf)
  }, [phase])

  // Which tier owns the focus panel. During evaluation it's the tier being
  // evaluated (or most recent resolved). At end-state it's the hero tier.
  const heroTierIndex = (() => {
    const denied = scenario.tiers.find((t) => t.state === 'denied')
    if (denied) return denied.index
    const resolved = scenario.tiers.find((t) => t.state === 'resolved')
    return resolved?.index ?? null
  })()
  // Lock focused tier to the hero as soon as any tier has been evaluated — this
  // keeps the focus panel stable through the whole scenario instead of flipping
  // between intermediate tiers.
  const focusedTierIndex: number | null = phase === 0 ? null : heroTierIndex

  useEffect(() => {
    const reducedMotion =
      typeof window !== 'undefined' &&
      window.matchMedia('(prefers-reduced-motion: reduce)').matches
    if (reducedMotion) {
      setTyped(prompt.length)
      setPhase(4)
      return
    }

    const timers: ReturnType<typeof setTimeout>[] = []
    const intervals: ReturnType<typeof setInterval>[] = []

    // Typewriter
    const typer = setInterval(() => {
      setTyped((t) => {
        if (t >= prompt.length) {
          clearInterval(typer)
          return t
        }
        return t + 1
      })
    }, TYPE_INTERVAL_MS)
    intervals.push(typer)

    const t0 = prompt.length * TYPE_INTERVAL_MS + POST_TYPE_PAUSE_MS
    timers.push(setTimeout(() => setPhase(1), t0 + TIER_GAP_MS * 1))
    timers.push(setTimeout(() => setPhase(2), t0 + TIER_GAP_MS * 2))
    timers.push(setTimeout(() => setPhase(3), t0 + TIER_GAP_MS * 3))
    timers.push(setTimeout(() => setPhase(4), t0 + TIER_GAP_MS * 3 + ANSWER_GAP_MS))

    const exitAt = t0 + TIER_GAP_MS * 3 + ANSWER_GAP_MS + DWELL_MS
    timers.push(setTimeout(() => setExiting(true), exitAt))
    timers.push(setTimeout(onAdvance, exitAt + EXIT_MS))

    return () => {
      timers.forEach(clearTimeout)
      intervals.forEach(clearInterval)
    }
  }, [prompt, onAdvance])

  return (
    <div
      className="flex h-full flex-col transition-opacity duration-500 ease-out"
      style={{ opacity: exiting ? 0 : 1 }}
    >
      {/* Header */}
      <div className="flex flex-none items-center justify-between border-b border-rule px-6 py-2.5">
        <span className="font-mono text-[10px] uppercase tracking-[0.22em] text-ink-muted">
          resolution trace
        </span>
        <div className="flex items-center gap-4">
          <span className="font-mono text-[10px] text-ink-muted">
            {scenario.actor}
          </span>
          <ScenarioDots count={scenarioCount} activeIdx={scenarioIdx} />
        </div>
      </div>

      {/* Prompt (typewriter). Reserved 3-line height so any scenario wraps
          without clipping and without shifting the content below. Text hugs
          the top of the container so short prompts don't drift downward.
          Once typing completes, the scenario's authored highlight spans
          (ontology classes, metric filters, denied scopes) settle in with a
          soft terracotta wash to show what the tiers actually bound. */}
      <div className="flex h-[128px] flex-none items-start px-6 pb-2 pt-4">
        <p
          className="font-display text-[22.5px] leading-[1.32] text-ink"
          style={{ fontVariationSettings: '"opsz" 96', fontWeight: 400 }}
          aria-label={prompt}
        >
          <PromptText
            prompt={prompt}
            typed={typed}
            highlights={scenario.highlights}
            phase={phase}
          />
          {typed < prompt.length && (
            <span
              aria-hidden="true"
              className="trace-caret ml-[1px] inline-block h-[0.9em] w-[2px] translate-y-[3px] bg-terracotta align-middle"
            />
          )}
        </p>
      </div>

      {/* Tier list with inline expansion under the focused tier. The list
          sits in the flex-1 middle zone between the fixed header/prompt and
          the pinned answer footer, and scrolls vertically if its content
          exceeds the available space (tall snippet + long facts). */}
      <ol
        ref={tierListRef}
        className="trace-scroll relative min-h-0 flex-1 overflow-y-auto border-t border-rule/70 px-6 py-3"
      >
        {scenario.tiers.map((tier, i) => {
          const revealed = phase >= (tier.index as Phase)
          const showEvaluating =
            !revealed && phase === ((tier.index - 1) as Phase)
          const isFocused = focusedTierIndex === tier.index
          const isResolved = tier.state === 'resolved'
          const isDenied = tier.state === 'denied'
          const isNotReached = tier.state === 'not-reached'
          const isLast = i === scenario.tiers.length - 1
          const threadActive = isResolved
          const threadBlocked = isDenied

          return (
            <li key={tier.index} className="relative py-2">
              {/* Connector line centered under the 20px circle's center
                  (circle lives in col 1 which is 24px wide, so center = 12px
                  from the li's left edge). */}
              {!isLast && (
                <span
                  aria-hidden="true"
                  className={[
                    'absolute left-[11.5px] top-[34px] bottom-0 w-px origin-top transition-transform duration-700 ease-out',
                    revealed ? 'scale-y-100' : 'scale-y-0',
                    threadActive
                      ? 'bg-terracotta/35'
                      : threadBlocked
                        ? 'bg-terracotta/20'
                        : 'bg-ink/10',
                  ].join(' ')}
                />
              )}

              {/* First line: circle + title + state chip, all items-center
                  so the number reads centered against the title baseline. */}
              <div className="grid grid-cols-[24px_1fr_auto] items-center gap-x-3.5">
                <span
                  aria-hidden="true"
                  className={[
                    'flex h-5 w-5 flex-none items-center justify-center rounded-full font-mono text-[11px] leading-none tracking-wide transition-colors duration-500',
                    !revealed
                      ? showEvaluating
                        ? 'text-ink-muted'
                        : 'text-ink-faint/40'
                      : isResolved || isDenied
                        ? 'bg-terracotta/10 font-semibold text-terracotta'
                        : isNotReached
                          ? 'text-ink-faint'
                          : 'text-ink-muted',
                    isFocused ? 'ring-1 ring-terracotta/30' : '',
                  ].join(' ')}
                >
                  {tier.index}
                </span>

                <span
                  className={[
                    'font-display text-[14.5px] leading-none transition-colors duration-500',
                    !revealed
                      ? 'text-ink-faint/55'
                      : isResolved || isDenied
                        ? 'font-medium text-ink'
                        : isNotReached
                          ? 'text-ink-muted'
                          : 'text-ink-soft line-through decoration-ink/20',
                  ].join(' ')}
                  style={{ fontVariationSettings: '"opsz" 48' }}
                >
                  {tier.name}
                </span>

                <span
                  className="transition-opacity duration-500"
                  style={{ opacity: revealed ? 1 : 0 }}
                >
                  {isResolved ? (
                    <span className="flex items-center gap-2">
                      <span className="h-1.5 w-1.5 rounded-full bg-terracotta trace-breathe" />
                      <span className="font-mono text-[10px] uppercase tracking-[0.2em] text-terracotta">
                        resolved
                      </span>
                    </span>
                  ) : isDenied ? (
                    <span className="flex items-center gap-2">
                      <span className="h-1.5 w-1.5 rounded-sm bg-terracotta" />
                      <span className="font-mono text-[10px] uppercase tracking-[0.2em] text-terracotta">
                        blocked
                      </span>
                    </span>
                  ) : showEvaluating ? (
                    <span className="font-mono text-[10px] uppercase tracking-[0.2em] text-ink-muted">
                      evaluating…
                    </span>
                  ) : (
                    <span className="font-mono text-[10px] uppercase tracking-[0.2em] text-ink-faint">
                      {isNotReached ? 'deferred' : 'skipped'}
                    </span>
                  )}
                </span>
              </div>

              {/* Details + inline expansion indented under the title. When
                  the tier hasn't been evaluated yet, this block collapses to
                  zero height so unresolved tiers sit close to each other. */}
              <div className="pl-[38px]">
                {tier.detail && (
                  <div
                    className="overflow-hidden font-mono text-[10px] leading-snug text-ink-muted transition-all duration-500 ease-out"
                    style={{
                      opacity: revealed ? 1 : 0,
                      maxHeight: revealed ? 20 : 0,
                      marginTop: revealed ? 3 : 0,
                    }}
                  >
                    {tier.detail}
                  </div>
                )}
                <TierExpansion tier={tier} open={isFocused && revealed} />
              </div>
            </li>
          )
        })}
      </ol>

      {/* Answer: fixed height, pinned to bottom, fades on reveal. The
          footer is visually weighted a touch heavier than the tier list —
          deeper paper tint, slightly firmer top rule, and a soft terracotta
          accent strip at the very top — so the final outcome reads as the
          payoff without shouting. */}
      <div
        className="relative flex h-[156px] flex-none flex-col justify-center border-t border-ink/12 bg-paper-deep/70 px-6 py-4 transition-opacity duration-700 ease-out"
        style={{ opacity: phase >= 4 ? 1 : 0 }}
      >
        <span
          aria-hidden="true"
          className="trace-accent-strip pointer-events-none absolute inset-x-0 top-0 h-[2px]"
        />
        <AnswerPanel answer={scenario.answer} outcome={scenario.outcome} reveal={phase >= 4} />
      </div>
    </div>
  )
}

/**
 * Renders the prompt with authored highlight spans. Text is always fully
 * visible so the typewriter doesn't produce blank gaps; each highlight's
 * pale wash fades in when its tier resolves (phase >= tier) — the prompt
 * becomes a live map of what got bound at each step.
 */
function PromptText({
  prompt,
  typed,
  highlights,
  phase,
}: {
  prompt: string
  typed: number
  highlights: Scenario['highlights']
  phase: Phase
}): React.JSX.Element {
  if (!highlights || highlights.length === 0) {
    return <span aria-hidden="true">{prompt.slice(0, typed)}</span>
  }

  // Resolve each highlight to its [start, end) range. Drop any range that
  // overlaps an earlier one so we never render nested highlights.
  type Range = { start: number; end: number; tier: 1 | 2 | 3 }
  const ranges: Range[] = []
  for (const h of highlights) {
    const idx = prompt.indexOf(h.text)
    if (idx < 0) continue
    const next: Range = { start: idx, end: idx + h.text.length, tier: h.tier }
    if (ranges.some((r) => !(next.end <= r.start || next.start >= r.end))) continue
    ranges.push(next)
  }
  ranges.sort((a, b) => a.start - b.start)

  const parts: React.JSX.Element[] = []
  let cursor = 0
  let key = 0
  const pushPlain = (from: number, to: number): void => {
    if (from >= to) return
    parts.push(<span key={key++}>{prompt.slice(from, to)}</span>)
  }
  const pushHighlight = (r: Range, to: number): void => {
    if (r.start >= to) return
    const visible = phase >= r.tier
    parts.push(
      <span
        key={key++}
        className="trace-highlight"
        style={{
          ['--hl-alpha' as string]: visible ? '0.10' : '0',
        }}
      >
        {prompt.slice(r.start, to)}
      </span>,
    )
  }

  for (const r of ranges) {
    if (cursor >= typed) break
    const plainEnd = Math.min(r.start, typed)
    pushPlain(cursor, plainEnd)
    if (typed <= r.start) {
      cursor = typed
      break
    }
    const hlEnd = Math.min(r.end, typed)
    pushHighlight(r, hlEnd)
    cursor = hlEnd
  }
  pushPlain(cursor, typed)

  return <span aria-hidden="true">{parts}</span>
}

function TierExpansion({
  tier,
  open,
}: {
  tier: TierRow
  open: boolean
}): React.JSX.Element {
  const isDenied = tier.state === 'denied'
  const hasContent = Boolean(tier.snippet || (tier.facts && tier.facts.length > 0))
  if (!hasContent) return <></>

  return (
    <div
      className="overflow-hidden transition-all duration-500 ease-out"
      style={{
        opacity: open ? 1 : 0,
        maxHeight: open ? 480 : 0,
        marginTop: open ? 10 : 0,
      }}
    >
      {tier.snippet && (
        <>
          <div className="mb-1.5 font-mono text-[9px] uppercase tracking-[0.22em] text-ink-faint">
            {tier.snippet.lang}
          </div>
          <pre
            className={[
              'whitespace-pre-wrap break-words rounded-md border px-3 py-2 font-mono text-[10px] leading-[1.55]',
              isDenied
                ? 'border-terracotta/25 bg-terracotta/[0.03] text-ink-soft'
                : 'border-rule bg-paper-deep/40 text-ink-soft',
            ].join(' ')}
            style={{ overflow: 'hidden', wordBreak: 'break-word' }}
          >
            {tier.snippet.body}
          </pre>
        </>
      )}
      {tier.facts && tier.facts.length > 0 && (
        <dl className="mt-2.5 flex flex-wrap gap-x-4 gap-y-1 font-mono text-[9.5px]">
          {tier.facts.map((fact) => (
            <div key={fact.label} className="flex items-baseline gap-1.5">
              <dt className="uppercase tracking-[0.18em] text-ink-faint">
                {fact.label}
              </dt>
              <dd
                className={
                  fact.tone === 'positive' || fact.tone === 'warning'
                    ? 'text-terracotta'
                    : 'text-ink-soft'
                }
              >
                {fact.value}
              </dd>
            </div>
          ))}
        </dl>
      )}
    </div>
  )
}

function ScenarioDots({ count, activeIdx }: { count: number; activeIdx: number }): React.JSX.Element {
  return (
    <span className="flex items-center gap-1.5" aria-hidden="true">
      {Array.from({ length: count }, (_, i) => (
        <span
          key={i}
          className={[
            'h-1 rounded-full transition-all duration-500',
            i === activeIdx ? 'w-5 bg-ink/50' : 'w-1 bg-ink/20',
          ].join(' ')}
        />
      ))}
    </span>
  )
}

type BadgeTone = 'positive' | 'warning' | 'denial' | 'neutral'

function OutcomeBadge({
  label,
  tone,
}: {
  label: string
  tone: BadgeTone
}): React.JSX.Element {
  const styles: Record<BadgeTone, { wrap: string; dot: string }> = {
    positive: {
      wrap: 'border-terracotta/30 bg-terracotta/[0.06] text-terracotta',
      dot: 'bg-terracotta trace-breathe',
    },
    warning: {
      wrap: 'border-terracotta/30 bg-terracotta/[0.05] text-terracotta',
      dot: 'bg-terracotta',
    },
    denial: {
      wrap: 'border-terracotta/35 bg-terracotta/[0.08] text-terracotta',
      dot: 'bg-terracotta rounded-sm',
    },
    neutral: {
      wrap: 'border-ink/15 bg-paper text-ink-muted',
      dot: 'bg-ink-muted/70',
    },
  }
  const s = styles[tone]
  const dotIsSquare = tone === 'denial'
  return (
    <span
      className={[
        'inline-flex items-center gap-1.5 rounded-full border px-2.5 py-[3px] font-mono text-[9.5px] uppercase tracking-[0.2em]',
        s.wrap,
      ].join(' ')}
    >
      <span
        aria-hidden="true"
        className={[
          'h-1.5 w-1.5',
          dotIsSquare ? '' : 'rounded-full',
          s.dot,
        ].join(' ')}
      />
      {label}
    </span>
  )
}

function AnswerPanel({
  answer,
  outcome,
  reveal,
}: {
  answer: Answer
  outcome: Scenario['outcome']
  reveal: boolean
}): React.JSX.Element {
  if (answer.kind === 'grid') {
    return (
      <>
        <div className="flex items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            <span className="font-mono text-[10px] uppercase tracking-[0.22em] text-ink-muted">
              answer
            </span>
            <OutcomeBadge label={outcome.label} tone="positive" />
          </div>
          <span className="truncate font-mono text-[10px] text-ink-muted">
            provenance · {answer.provenance}
          </span>
        </div>
        <div className="mt-3 grid grid-cols-4 gap-3">
          {answer.rows.map((row, i) => (
            <div
              key={row.label}
              className="transition-all duration-500 ease-out"
              style={{
                opacity: reveal ? 1 : 0,
                transform: reveal ? 'translateY(0)' : 'translateY(6px)',
                transitionDelay: reveal ? `${i * 90}ms` : '0ms',
              }}
            >
              <div
                className="font-display text-[21px] font-medium leading-none text-ink"
                style={{ fontVariationSettings: '"opsz" 96' }}
              >
                {row.value}
              </div>
              <div className="mt-1.5 font-mono text-[9.5px] uppercase tracking-[0.18em] text-ink-muted">
                {row.label}
              </div>
            </div>
          ))}
        </div>
      </>
    )
  }

  if (answer.kind === 'narrative') {
    return (
      <>
        <div className="flex items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            <span className="font-mono text-[10px] uppercase tracking-[0.22em] text-ink-muted">
              narrative
            </span>
            <OutcomeBadge label={outcome.label} tone="positive" />
          </div>
          <span className="truncate font-mono text-[10px] text-ink-muted">
            provenance · {answer.provenance}
          </span>
        </div>
        <div
          className="mt-2 transition-all duration-500 ease-out"
          style={{
            opacity: reveal ? 1 : 0,
            transform: reveal ? 'translateY(0)' : 'translateY(6px)',
          }}
        >
          <div
            className="font-display text-[15px] font-medium leading-snug text-ink"
            style={{ fontVariationSettings: '"opsz" 72' }}
          >
            {answer.headline}
          </div>
          <p className="mt-1.5 line-clamp-2 text-[12px] leading-[1.5] text-ink-soft">
            {answer.body}
          </p>
        </div>
      </>
    )
  }

  if (answer.kind === 'single') {
    return (
      <>
        <div className="flex items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            <span className="font-mono text-[10px] uppercase tracking-[0.22em] text-ink-muted">
              answer
            </span>
            <OutcomeBadge label={outcome.label} tone="positive" />
          </div>
          <span className="truncate font-mono text-[10px] text-ink-muted">
            provenance · {answer.provenance}
          </span>
        </div>
        <div className="mt-3 flex items-center gap-4">
          <span
            className="font-display text-[38px] font-medium leading-none text-ink transition-all duration-500 ease-out"
            style={{
              fontVariationSettings: '"opsz" 144',
              letterSpacing: '-0.02em',
              opacity: reveal ? 1 : 0,
              transform: reveal ? 'translateY(0)' : 'translateY(6px)',
            }}
          >
            {answer.value}
          </span>
          <span className="max-w-[55%] font-mono text-[11px] leading-[1.4] uppercase tracking-[0.2em] text-ink-muted">
            {answer.label}
          </span>
        </div>
      </>
    )
  }

  // denied
  return (
    <>
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-mono text-[10px] uppercase tracking-[0.22em] text-ink-muted">
          denial
        </span>
        <OutcomeBadge label={outcome.label} tone="denial" />
        <OutcomeBadge label="audit recorded" tone="neutral" />
      </div>
      <div className="mt-1 font-mono text-[10px] text-ink-muted">
        policy · {answer.policy}
      </div>
      <p
        className="mt-2 line-clamp-2 text-[12.5px] leading-[1.5] text-ink-soft transition-all duration-500 ease-out"
        style={{
          opacity: reveal ? 1 : 0,
          transform: reveal ? 'translateY(0)' : 'translateY(6px)',
        }}
      >
        {answer.reason}
      </p>
    </>
  )
}
