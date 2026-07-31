// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

export const layoutConfig = {
  name: "fcose",
  quality: "default",
  randomize: true,
  animate: false,
  // Tuned for a spacious, breathable layout — nodes shouldn't feel crammed.
  // Slightly higher repulsion + edge length vs defaults creates negative space
  // that lets the module color clusters emerge naturally.
  nodeRepulsion: 8000,
  idealEdgeLength: 100,
  edgeElasticity: 0.4,
  gravity: 0.2,
  gravityRange: 120,
  nodeSeparation: 85,
  numIter: 2500,
  tilingPaddingVertical: 20,
  tilingPaddingHorizontal: 20,
};
