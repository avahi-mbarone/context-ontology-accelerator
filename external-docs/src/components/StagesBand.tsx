// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

type Stage = {
  index: string;
  name: string;
  blurb: string;
  artifacts: string[];
  page: string;
};

const STAGES: Stage[] = [
  {
    index: "01",
    name: "Scan",
    blurb:
      "Connect to your structured and unstructured data estate. Enable AI-based enrichment for business metadata and entity extraction, with embeddings for retrieval. Set the foundation for ontology modeling.",
    artifacts: ["Glue Data Catalog", "JDBC databases", "Document ingestion"],
    page: "sources",
  },
  {
    index: "02",
    name: "Model",
    blurb:
      "Create a proposal with AI-assisted ontology induction and ground it to industry or customer-defined ontologies. Review, edit, and publish through human-in-the-loop into a knowledge graph. Separately, define governed metrics to allow for pre-computed business KPIs.",
    artifacts: [
      "OWL 2 classes",
      "R2RML mappings",
      "SHACL shapes",
      "Governed metrics",
    ],
    page: "ontologies",
  },
  {
    index: "03",
    name: "Serve",
    blurb:
      "Use the built-in playground or the MCP tools to connect agents — agent-agnostic to meet users and agents where they are. Tiered context resolution and execution: from governed metrics, to structured ontology query over the virtual knowledge graph, to agentic fallback with knowledge synthesis. Each resolution path is designed to enforce Cedar two-layer authorization and the SQL Firewall.",
    artifacts: ["MCP server · REST", "Cedar policies", "SQL Firewall (AST)"],
    page: "serve",
  },
];

export function StagesBand(): React.JSX.Element {
  return (
    <section className="border-t border-rule bg-paper-deep/40">
      <div className="mx-auto w-full max-w-7xl px-6 py-24 sm:px-10 sm:py-28 lg:px-14 lg:py-32">
        <div className="grid gap-14 lg:grid-cols-[0.8fr_1.2fr] lg:gap-24">
          <div className="min-w-0">
            <span className="display-eyebrow">How it works</span>
            <h2 className="display-h2 mt-5 text-[clamp(2.25rem,4.4vw,3.5rem)] text-ink">
              Three stages.
              <br />
              One context model.
            </h2>
            <p className="mt-6 max-w-sm text-[15.5px] leading-relaxed text-ink-soft">
              Scan your data. Model your business. Serve your agents. Govern
              answers. Built on W3C standards, delivered over MCP.
            </p>
          </div>

          <div className="relative min-w-0">
            <div
              aria-hidden="true"
              className="absolute left-[18px] top-[34px] h-[calc(100%-68px)] w-px bg-gradient-to-b from-terracotta/40 via-ink/15 to-transparent"
            />
            <ol className="space-y-12">
              {STAGES.map((stage) => (
                <li key={stage.index} className="relative pl-14">
                  <div className="absolute left-0 top-1 flex h-9 w-9 items-center justify-center rounded-full border border-ink/15 bg-paper">
                    <span className="font-mono text-[11px] font-medium text-terracotta">
                      {stage.index}
                    </span>
                  </div>
                  <a href={`#/${stage.page}`} className="block group">
                    <h3
                      className="font-display text-[28px] font-medium leading-tight text-ink group-hover:text-terracotta transition-colors"
                      style={{ fontVariationSettings: '"opsz" 72' }}
                    >
                      {stage.name}
                    </h3>
                  </a>
                  <p className="mt-3 max-w-xl text-[15px] leading-relaxed text-ink-soft">
                    {stage.blurb}
                  </p>
                  <div className="mt-4 flex flex-wrap gap-x-4 gap-y-1.5">
                    {stage.artifacts.map((artifact) => (
                      <span
                        key={artifact}
                        className="font-mono text-[11.5px] tracking-wide text-ink-muted"
                      >
                        {artifact}
                      </span>
                    ))}
                  </div>
                </li>
              ))}
            </ol>
          </div>
        </div>
      </div>
    </section>
  );
}
