// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

export interface SequentialResult<T> {
  /** Items whose operation resolved, in input order. */
  succeeded: T[];
  /** Items whose operation rejected, in input order. */
  failed: T[];
}

/**
 * Runs an async operation for each item strictly one-at-a-time, awaiting each
 * before starting the next, and continues past individual failures.
 *
 * Use this for per-item operations that are NOT safe to run concurrently. The
 * motivating case is per-column review: on the backend each call is a full
 * read-modify-write of the shared table asset (load asset → flip one column →
 * write a new revision). Firing those in parallel makes the writes race off the
 * same baseline revision and clobber each other, so only the last writer's
 * column survives. Running sequentially means each call observes the revision
 * the previous one just wrote.
 */
export async function runSequential<T>(
  items: readonly T[],
  run: (item: T) => Promise<unknown>,
): Promise<SequentialResult<T>> {
  const succeeded: T[] = [];
  const failed: T[] = [];
  for (const item of items) {
    try {
      await run(item);
      succeeded.push(item);
    } catch {
      failed.push(item);
    }
  }
  return { succeeded, failed };
}
