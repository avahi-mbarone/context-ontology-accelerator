// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

// Monochrome node system — color is reserved exclusively for status.
// Module identity comes from spatial clustering and labels, not fill color.

// Neutral fills: hero nodes get a slightly more present surface;
// induced nodes are more ghostly.
const LIGHT = {
  heroFill: "#cbd5e1",
  heroBorder: "#64748b",
  inducedFill: "#e2e8f0",
  inducedBorder: "#94a3b8",
};

const DARK = {
  heroFill: "#334155",
  heroBorder: "#64748b",
  inducedFill: "#1e293b",
  inducedBorder: "#475569",
};

export function colorForType(
  _typeIri: string | undefined,
  mode: "light" | "dark" = "light",
): string {
  return mode === "dark" ? DARK.heroBorder : LIGHT.heroBorder;
}

export function tintForType(
  _typeIri: string | undefined,
  mode: "light" | "dark" = "light",
): string {
  return mode === "dark" ? DARK.heroFill : LIGHT.heroFill;
}

export function inducedColor(mode: "light" | "dark" = "light"): {
  fill: string;
  border: string;
} {
  return mode === "dark"
    ? { fill: DARK.inducedFill, border: DARK.inducedBorder }
    : { fill: LIGHT.inducedFill, border: LIGHT.inducedBorder };
}

// Node sizing: logarithmic scale with dramatic range for visual hierarchy.
export function sizeForInstances(instances: number | undefined): number {
  if (!instances || instances <= 0) return 22;
  const s = Math.log10(instances + 1);
  return Math.min(64, Math.max(22, 8 * s));
}
