// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

/** Namespace lifecycle statuses (LLD §2.3). */
export enum NamespaceStatus {
  ACTIVE = "ACTIVE",
  SUSPENDED = "SUSPENDED",
  ARCHIVED = "ARCHIVED",
  DELETED = "DELETED",
}

/** Namespace ID prefix. */
export const NAMESPACE_ID_PREFIX = "ns";
