// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Turn heading text into a URL fragment, matching MkDocs' slug format.
 *
 * The markdown in `content/` is written against MkDocs, whose in-page links
 * (`[text](#some-heading)`) rely on auto-generated heading ids. `react-markdown`
 * does not generate them, so `MarkdownPage` applies this to headings and
 * `DeployingSidebar` applies it to look them up — both must agree, hence one
 * shared implementation rather than a copy in each.
 *
 * Example: `"Appendix A — AWS Service Inventory, Quotas, and Considerations"`
 * becomes `"appendix-a-aws-service-inventory-quotas-and-considerations"`.
 */
export function slugify(text: string): string {
  return text
    .toLowerCase()
    .replace(/[^\w\s-]/g, "")
    .replace(/\s+/g, "-")
    .replace(/-+/g, "-")
    .trim();
}
