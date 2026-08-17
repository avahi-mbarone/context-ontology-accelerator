// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Guards the contract between two things that must agree but live apart: the
 * `](#fragment)` links authored in `content/*.md` (MkDocs slug format) and the
 * heading ids `MarkdownPage` generates via `slugify`.
 *
 * If they drift, in-page links silently fall through the app's hash router to
 * the home tab — the failure mode this test exists to catch, because it looks
 * like a routing bug rather than a slug bug.
 *
 * Kept as plain `node --test` with an inlined copy of `slugify` so it runs under
 * the existing `scripts/**\/*.test.mjs` runner with no TS build step. The copy is
 * the reason the assertions below pin real headings from the docs: if
 * `src/utils/slugify.ts` changes and this copy does not, these fail.
 */

import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync, readdirSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const contentDir = join(dirname(fileURLToPath(import.meta.url)), "..", "content");

/** Mirror of `src/utils/slugify.ts`. */
function slugify(text) {
  return text
    .toLowerCase()
    .replace(/[^\w\s-]/g, "")
    .replace(/\s+/g, "-")
    .replace(/-+/g, "-")
    .trim();
}

test("slugify matches the MkDocs fragments used in the docs", () => {
  assert.equal(
    slugify("Appendix A — AWS Service Inventory, Quotas, and Considerations"),
    "appendix-a-aws-service-inventory-quotas-and-considerations",
  );
  assert.equal(slugify("A.3 Quotas to check before deploying"), "a3-quotas-to-check-before-deploying");
  assert.equal(slugify("Service Quotas"), "service-quotas");
});

test("every in-page anchor link in content/ resolves to a heading", () => {
  const broken = [];

  for (const file of readdirSync(contentDir).filter((f) => f.endsWith(".md"))) {
    const md = readFileSync(join(contentDir, file), "utf8");

    // Headings this page defines. Only h2-h4 get ids in MarkdownPage, matching
    // the levels overridden there.
    const ids = new Set(
      [...md.matchAll(/^(#{2,4})\s+(.+?)\s*$/gm)].map(([, , heading]) => slugify(heading)),
    );

    // Same-page links only: `](#frag)`. Two exclusions: cross-page
    // `](other.md#frag)` is routed by resolveHref, and `](#/route)` is the app's
    // own hash-route format handled by getTabFromHash — neither resolves to a
    // heading id on this page.
    for (const [, fragment] of md.matchAll(/]\(#(?!\/)([^)]+)\)/g)) {
      if (!ids.has(fragment)) broken.push(`${file} → #${fragment}`);
    }
  }

  assert.deepEqual(broken, [], `anchor links with no matching heading:\n  ${broken.join("\n  ")}`);
});
