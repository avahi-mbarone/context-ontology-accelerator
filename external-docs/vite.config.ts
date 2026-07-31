// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { resolve } from 'node:path'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  // Absolute base so asset URLs resolve correctly regardless of the serving
  // path (GitHub Pages project subpath vs. local dev/preview at '/'). Override
  // via the VITE_BASE env var — the pages.yml workflow sets this to
  // PAGES_BASE ("/context-ontology-accelerator/") for the production build.
  base: process.env.VITE_BASE ?? '/',
  build: {
    outDir: 'dist',
  },
  resolve: {
    alias: {
      '@docs': resolve(__dirname, 'content'),
    },
  },
})
