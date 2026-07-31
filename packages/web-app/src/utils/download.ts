// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Client-side file download helper.
 *
 * Wraps the standard Blob + ``URL.createObjectURL`` + anchor-click + revoke
 * pattern so pages don't each re-implement it. Used for downloading Turtle
 * artifacts (induced ontologies, compiled SHACL shapes) straight from the
 * browser without a round-trip through the API.
 */
export function downloadTextFile(
  filename: string,
  text: string,
  mime = "text/turtle",
): void {
  const blob = new Blob([text], { type: mime });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}
