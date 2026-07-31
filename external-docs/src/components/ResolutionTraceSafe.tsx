// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { Component, type ReactNode } from 'react'
import { ResolutionTrace } from './ResolutionTrace'

type State = { hasError: boolean }

/**
 * Error boundary around the animated ResolutionTrace card so that any runtime
 * failure inside it (hook timing, DOM animation API, etc.) cannot break the
 * Hero section or the rest of the landing page. In the error state the slot
 * collapses to nothing rather than showing a loud fallback.
 */
export class ResolutionTraceSafe extends Component<Record<string, never>, State> {
  override state: State = { hasError: false }

  static getDerivedStateFromError(): State {
    return { hasError: true }
  }

  override componentDidCatch(error: unknown): void {
    if (typeof console !== 'undefined') {
      // eslint-disable-next-line no-console
      console.warn('[ResolutionTrace] fell back to safe mode:', error)
    }
  }

  override render(): ReactNode {
    if (this.state.hasError) {
      return null
    }
    return <ResolutionTrace />
  }
}
