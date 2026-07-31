// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { lazy, Suspense } from "react";
import { scalarCustomCss } from "../styles/scalar-theme";

// Lazy-load Scalar so its bundle does not affect first paint of the main docs
// (mirrors the lazy-mermaid pattern in MarkdownPage.tsx).
const ApiReferenceReact = lazy(async () => {
  const mod = await import("@scalar/api-reference-react");
  await import("@scalar/api-reference-react/style.css");
  return { default: mod.ApiReferenceReact };
});

export function ApiReference(): React.JSX.Element {
  return (
    <Suspense
      fallback={
        <div className="py-24 text-center text-ink-muted">
          Loading API reference…
        </div>
      }
    >
      <ApiReferenceReact
        configuration={{
          customCss: scalarCustomCss,
          hideModels: false,
          // Opt out of Scalar's PostHog usage analytics.
          telemetry: false,
          // Hide the developer-tools toolbar (the "Deploy"/"Share on Scalar"
          // buttons). Defaults to 'localhost', so it must be set to 'never'.
          showDeveloperTools: "never",
          sources: [
            {
              url: "./api/control-plane.openapi.json",
              title: "Control Plane API",
              slug: "control-plane",
              default: true,
              // Disable Scalar's "Ask AI" agent. Without this it renders on
              // local URLs by default (and on any URL if an agent key is set).
              agent: { disabled: true },
            },
            {
              url: "./api/data-layer.openapi.json",
              title: "Data Layer (Serve) API",
              slug: "data-layer",
              agent: { disabled: true },
            },
          ],
        }}
      />
    </Suspense>
  );
}
