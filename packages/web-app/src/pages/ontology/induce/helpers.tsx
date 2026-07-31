// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import Badge from "@cloudscape-design/components/badge";
import StatusIndicator from "@cloudscape-design/components/status-indicator";
import { ProposalStatus } from "@coa/control-plane-client";

export function shortId(id: string, len = 8): string {
  return id.length > len ? `${id.slice(0, len)}…` : id;
}

/**
 * Proposal statuses that mean an accept is in flight: a worker is (or was)
 * running, so Accept must stay disabled and the detail page should keep polling.
 * Mirrors the backend's ``_ACCEPT_IN_PROGRESS_STATUSES`` (proposals.py).
 *
 * Values come from the Smithy-generated ``ProposalStatus`` — the API contract is
 * the single source of truth, so a wire value can't drift from what the UI
 * compares against. Single definition on purpose: these were previously compared
 * as inline literals at three separate sites, and missing the Accept-button check
 * would re-enable Accept during a live accept.
 */
export const PROPOSAL_IN_PROGRESS_STATUSES: ReadonlySet<string> = new Set([
  ProposalStatus.ACCEPTING,
  ProposalStatus.EMBEDDINGS_SYNC,
]);

export function isProposalAcceptInProgress(status: string): boolean {
  return PROPOSAL_IN_PROGRESS_STATUSES.has(status);
}

/**
 * Has an in-flight accept reached a terminal FAILURE the poll loop should stop
 * on? (#456/#466/#467)
 *
 *   - ``accept_failed`` — the worker's terminal failure state: a pipeline step
 *     exhausted its retries. Always carries ``accept_error`` naming the step.
 *   - ``pending`` + ``accept_error`` — the LEGACY failure shape (the worker used
 *     to roll back to ``pending``). Still honoured so a proposal that failed
 *     under an older deployment is reported rather than polled to timeout.
 *   - bare ``pending`` (no error) is NOT a failure: it's the initial state of
 *     every fresh proposal, seen while the ``accepting`` flip propagates.
 *
 * Pure helper so the decision is unit-testable without rendering ProposalDetail
 * under jsdom fake timers.
 */
export function isAcceptTerminalFailure(proposal: {
  status: string;
  accept_error?: string;
}): boolean {
  if (proposal.status === ProposalStatus.ACCEPT_FAILED) return true;
  return (
    proposal.status === ProposalStatus.PENDING && Boolean(proposal.accept_error)
  );
}

/**
 * Does this proposal block starting a NEW induction for its ontology?
 *
 * Must match the backend guard (``PROPOSAL_STATUSES_BLOCKING_NEW_INDUCTION`` in
 * proposals.py) or the button stays enabled and the request 409s. Two kinds of
 * "not finished with this one":
 *
 *   - unreviewed work: ``inducing`` (still being produced), ``pending`` /
 *     ``updated`` / ``accept_failed`` (awaiting review). ``accept_failed`` counts
 *     because before that state existed a failed accept rolled back to
 *     ``pending``, which blocked.
 *   - an accept actively merging: ``accepting`` / ``embeddings_sync``. The
 *     backend's induction lock only spans an INDUCTION, so without these a new
 *     induction can start mid-merge and leave two competing proposals.
 */
export const PROPOSAL_BLOCKS_NEW_INDUCTION_STATUSES: ReadonlySet<string> =
  new Set([
    ProposalStatus.INDUCING,
    ProposalStatus.PENDING,
    ProposalStatus.UPDATED,
    ProposalStatus.ACCEPT_FAILED,
    ...PROPOSAL_IN_PROGRESS_STATUSES,
  ]);

export function proposalBlocksNewInduction(status: string): boolean {
  return PROPOSAL_BLOCKS_NEW_INDUCTION_STATUSES.has(status);
}

export function proposalStatusIndicator(status: string) {
  switch (status) {
    case "pending":
      return <StatusIndicator type="pending">Pending</StatusIndicator>;
    case "accepting":
      return <StatusIndicator type="in-progress">Accepting…</StatusIndicator>;
    case "embeddings_sync":
      return (
        <StatusIndicator type="in-progress">
          Syncing embeddings…
        </StatusIndicator>
      );
    case "accepted":
      return <StatusIndicator type="success">Accepted</StatusIndicator>;
    // An accept whose pipeline step exhausted its retries. The proposal is
    // still re-acceptable; ``accept_error`` names the failing step.
    case "accept_failed":
      return <StatusIndicator type="error">Accept failed</StatusIndicator>;
    case "rejected":
      return <StatusIndicator type="error">Rejected</StatusIndicator>;
    case "cancelled":
      return <StatusIndicator type="stopped">Cancelled</StatusIndicator>;
    case "updated":
      return <StatusIndicator type="in-progress">Updated</StatusIndicator>;
    default:
      return <Badge>{status}</Badge>;
  }
}
