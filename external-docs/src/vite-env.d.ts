// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

/// <reference types="vite/client" />

declare module '@docs/*.md?raw' {
  const content: string
  export default content
}

declare module '*.md?raw' {
  const content: string
  export default content
}
