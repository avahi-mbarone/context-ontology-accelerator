// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { Component, type ReactNode } from 'react'
import { ApiReference } from './ApiReference'

type State = { hasError: boolean }

/**
 * Error boundary around the lazily-loaded Scalar API reference. `lazy()` throws
 * if the chunk fails to load (offline, missing asset, or a runtime error inside
 * Scalar); Suspense only handles the pending state, not the rejection. Without a
 * boundary that rejection would unmount the whole docs app, so this catches it
 * and shows a self-contained fallback instead. Mirrors ResolutionTraceSafe.
 */
export class ApiReferenceSafe extends Component<Record<string, never>, State> {
  override state: State = { hasError: false }

  static getDerivedStateFromError(): State {
    return { hasError: true }
  }

  override componentDidCatch(error: unknown): void {
    if (typeof console !== 'undefined') {
      // eslint-disable-next-line no-console
      console.warn('[ApiReference] failed to load:', error)
    }
  }

  override render(): ReactNode {
    if (this.state.hasError) {
      return (
        <div className="py-24 text-center text-ink-muted">
          The API reference failed to load. Please refresh the page to try again.
        </div>
      )
    }
    return <ApiReference />
  }
}
