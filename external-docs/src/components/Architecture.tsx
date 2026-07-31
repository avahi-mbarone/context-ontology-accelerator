// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

type Service = {
  role: string;
  name: string;
};

const SERVICES: Service[] = [
  { role: "Graph", name: "Amazon Neptune" },
  { role: "Vectors + search", name: "Amazon OpenSearch" },
  { role: "Documents & TTL", name: "Amazon S3" },
  { role: "Operational state", name: "Amazon DynamoDB" },
  { role: "Enrichment", name: "Amazon Bedrock" },
  { role: "Catalog sources", name: "AWS Glue · SageMaker" },
];

export function Architecture(): React.JSX.Element {
  return (
    <section className="border-t border-rule bg-paper-deep/40">
      <div className="mx-auto w-full max-w-7xl px-6 py-24 sm:px-10 sm:py-28 lg:px-14 lg:py-28">
        <div className="grid gap-16 lg:grid-cols-[0.9fr_1.1fr] lg:gap-24">
          <div className="min-w-0">
            <span className="display-eyebrow">Open Source · Apache 2.0</span>
            <h2 className="display-h2 mt-5 text-[clamp(2rem,4vw,3rem)] text-ink">
              Built on AWS.
              <br />
              Portable by design.
            </h2>
            <p className="mt-6 max-w-md text-[15.5px] leading-relaxed text-ink-soft">
              This solution is designed and deployed natively on AWS services.
              The project is open source under Apache 2.0 and built on open
              standards — W3C (OWL, RDF, SHACL, SPARQL), MCP, and Apache OSSIE —
              providing you portability through these standards.
            </p>
          </div>

          <dl className="relative grid min-w-0 grid-cols-1 gap-y-5 sm:grid-cols-[auto_1fr] sm:gap-x-10 sm:border-l sm:border-rule sm:pl-10">
            {SERVICES.map((service) => (
              <div key={service.name} className="contents">
                <dt className="font-mono text-[11px] uppercase tracking-[0.18em] text-ink-muted">
                  {service.role}
                </dt>
                <dd
                  className="font-display text-[18px] font-medium leading-snug text-ink"
                  style={{ fontVariationSettings: '"opsz" 48' }}
                >
                  {service.name}
                </dd>
              </div>
            ))}
          </dl>
        </div>
      </div>
    </section>
  );
}
