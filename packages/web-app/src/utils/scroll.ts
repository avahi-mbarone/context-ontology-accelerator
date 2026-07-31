// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Find the nearest scrollable ancestor of a DOM element.
 * Returns null if no scrollable parent exists before document.body.
 */
export function findScrollParent(el: HTMLElement | null): HTMLElement | null {
  let current = el?.parentElement ?? null;
  while (current && current !== document.body) {
    if (current.scrollHeight > current.clientHeight + 5) {
      return current;
    }
    current = current.parentElement;
  }
  return null;
}

/**
 * Scroll the nearest scrollable ancestor of `el` to the bottom.
 */
export function scrollToBottom(el: HTMLElement | null): void {
  const scrollParent = findScrollParent(el);
  if (scrollParent) {
    scrollParent.scrollTop = scrollParent.scrollHeight;
  }
}
