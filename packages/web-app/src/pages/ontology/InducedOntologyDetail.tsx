// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Induced ontology detail page (route: /namespaces/:namespaceId/ontology/induced).
 *
 * Uses react-query hooks + the Smithy-generated TS client for data fetching.
 * The ontology IRI is passed as the ``ontology_id`` query param.
 */
import { useEffect, useState } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import Alert from "@cloudscape-design/components/alert";
import Badge from "@cloudscape-design/components/badge";
import Box from "@cloudscape-design/components/box";
import Button from "@cloudscape-design/components/button";
import Container from "@cloudscape-design/components/container";
import Header from "@cloudscape-design/components/header";
import KeyValuePairs from "@cloudscape-design/components/key-value-pairs";
import Link from "@cloudscape-design/components/link";
import SpaceBetween from "@cloudscape-design/components/space-between";
import Spinner from "@cloudscape-design/components/spinner";
import Tabs from "@cloudscape-design/components/tabs";
import { SortableTable } from "@components/SortableTable";
import { useOntologyOverview } from "@api-hooks/use-ontology-overview";
import { useListOntologies } from "@api-hooks/use-list-ontologies";
import { downloadOntology } from "../../services/ontology-engine";
import { downloadTextFile } from "@utils/download";
import { useApiClient } from "@components/ApiClientProvider";
import { useBreadcrumbs } from "@components/BreadcrumbProvider";
import { TurtleHighlight } from "@components/TurtleHighlight";
import { PendingReviewBanner } from "@components/ontology/PendingReviewBanner";

/** Strip an IRI down to its local name (after the last ``#`` or ``/``). */
export function localName(uri: string | undefined | null): string {
  if (!uri) return "—";
  // Strip trailing # or / before extracting
  const trimmed = uri.replace(/[#/]+$/, "");
  const hash = trimmed.lastIndexOf("#");
  const slash = trimmed.lastIndexOf("/");
  const idx = Math.max(hash, slash);
  return idx >= 0 && idx < trimmed.length - 1
    ? trimmed.slice(idx + 1)
    : trimmed;
}

export function InducedOntologyDetailPage() {
  const { namespaceId } = useParams<{ namespaceId: string }>();
  const [searchParams] = useSearchParams();
  const ontologyId = searchParams.get("ontology_id") ?? "";
  const navigate = useNavigate();
  const apiClient = useApiClient();

  const {
    data: overview,
    isLoading: loading,
    error,
  } = useOntologyOverview(namespaceId, ontologyId || undefined);
  const { data: ontologies } = useListOntologies(namespaceId);
  const record = ontologies?.find(
    (r) => r.ontologyId === ontologyId || r.uri === ontologyId,
  );

  // Breadcrumb: COA › Ontology › Induction › {Ontology}
  const { setBreadcrumbs, clearBreadcrumbs } = useBreadcrumbs();
  const ontologyLabel = record?.title || localName(ontologyId);
  useEffect(() => {
    setBreadcrumbs([
      { text: "COA", onClick: () => navigate("/") },
      { text: "Ontology" },
      {
        text: "Induction",
        onClick: () => navigate(`/namespaces/${namespaceId}/ontology`),
      },
      { text: ontologyLabel },
    ]);
    return () => clearBreadcrumbs();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [namespaceId, ontologyLabel]);

  const [activeTabId, setActiveTabId] = useState("classes");
  const [turtle, setTurtle] = useState<string | null>(null);
  const [turtleLoading, setTurtleLoading] = useState(false);
  const [turtleError, setTurtleError] = useState<string | null>(null);
  const [downloadBusy, setDownloadBusy] = useState(false);

  const classes = overview?.classes ?? [];
  const relationships = overview?.objectProperties ?? [];
  const attributes = overview?.datatypeProperties ?? [];

  async function ensureTurtle(): Promise<string | null> {
    if (turtle !== null) return turtle;
    if (!namespaceId || !ontologyId) return null;
    setTurtleLoading(true);
    setTurtleError(null);
    try {
      const text = await downloadOntology(apiClient, namespaceId, ontologyId);
      setTurtle(text);
      return text;
    } catch (e) {
      setTurtleError(
        e instanceof Error ? e.message : "Failed to load ontology source",
      );
      return null;
    } finally {
      setTurtleLoading(false);
    }
  }

  async function handleDownload() {
    setDownloadBusy(true);
    try {
      const text = await ensureTurtle();
      if (text === null) {
        // ensureTurtle set turtleError — switch to the Source tab so it's visible
        setActiveTabId("source");
        return;
      }
      const safeName = (record?.title || ontologyId)
        .replace(/[^A-Za-z0-9._-]/g, "_")
        .slice(0, 80);
      downloadTextFile(`${safeName || "ontology"}.ttl`, text);
    } finally {
      setDownloadBusy(false);
    }
  }

  function openClass(classUri: string) {
    navigate(
      `/namespaces/${namespaceId}/ontology/induced/class?ontology_id=${encodeURIComponent(
        ontologyId,
      )}&class_uri=${encodeURIComponent(classUri)}`,
    );
  }

  if (!ontologyId) {
    return (
      <Alert type="error" header="Missing ontology">
        No ontology was specified.
      </Alert>
    );
  }

  return (
    <SpaceBetween size="m">
      <PendingReviewBanner />
      <Header
        variant="h1"
        actions={
          <Button
            iconName="download"
            loading={downloadBusy}
            onClick={handleDownload}
          >
            Download .ttl
          </Button>
        }
        description={ontologyId}
      >
        Induced Ontology
      </Header>

      {error && (
        <Alert type="warning" header="Could not load graph contents">
          {error.message}
        </Alert>
      )}

      <Container>
        <KeyValuePairs
          columns={3}
          items={[
            { label: "Classes", value: String(classes.length) },
            { label: "Relationships", value: String(relationships.length) },
            { label: "Attributes", value: String(attributes.length) },
          ]}
        />
      </Container>

      <Tabs
        ariaLabel="Induced ontology graph contents"
        activeTabId={activeTabId}
        onChange={({ detail }) => {
          setActiveTabId(detail.activeTabId);
          if (detail.activeTabId === "source") void ensureTurtle();
        }}
        tabs={[
          {
            id: "classes",
            label: `Classes (${classes.length})`,
            content: (
              <SortableTable
                loading={loading}
                items={classes}
                trackBy="uri"
                variant="embedded"
                defaultSortingColumnId="name"
                columnDefinitions={[
                  {
                    id: "name",
                    header: "Class",
                    isRowHeader: true,
                    sortingComparator: (a, b) =>
                      (a.label || localName(a.uri)).localeCompare(
                        b.label || localName(b.uri),
                      ),
                    cell: (c) => (
                      <Link
                        onFollow={(ev) => {
                          ev.preventDefault();
                          openClass(c.uri!);
                        }}
                      >
                        {c.label || localName(c.uri)}
                      </Link>
                    ),
                  },
                  {
                    id: "origin",
                    header: "Origin",
                    // Grounded (0) sorts before Novel (1).
                    sortingComparator: (a, b) =>
                      (a.groundedTo ? 0 : 1) - (b.groundedTo ? 0 : 1),
                    cell: (c) =>
                      c.groundedTo ? (
                        <Badge color="blue">
                          {`Grounded${c.matchType ? ` (${c.matchType})` : ""}`}
                        </Badge>
                      ) : (
                        <Badge color="green">Novel</Badge>
                      ),
                  },
                  {
                    id: "groundedTo",
                    header: "Grounded to",
                    sortingComparator: (a, b) =>
                      (a.groundedTo
                        ? localName(a.groundedTo)
                        : ""
                      ).localeCompare(
                        b.groundedTo ? localName(b.groundedTo) : "",
                      ),
                    cell: (c) =>
                      c.groundedTo ? (
                        <span title={c.groundedTo}>
                          {localName(c.groundedTo)}
                        </span>
                      ) : (
                        "—"
                      ),
                  },
                  {
                    id: "comment",
                    header: "Description",
                    sortingComparator: (a, b) =>
                      (a.comment || "").localeCompare(b.comment || ""),
                    cell: (c) => c.comment || "—",
                  },
                ]}
                empty={
                  <Box textAlign="center" color="text-body-secondary">
                    No classes persisted in the graph yet. If you just accepted
                    a proposal, the graph may still be materializing — refresh
                    in a moment.
                  </Box>
                }
              />
            ),
          },
          {
            id: "relationships",
            label: `Relationships (${relationships.length})`,
            content: (
              <SortableTable
                loading={loading}
                items={relationships}
                trackBy="uri"
                variant="embedded"
                defaultSortingColumnId="name"
                columnDefinitions={[
                  {
                    id: "name",
                    header: "Relationship",
                    isRowHeader: true,
                    sortingComparator: (a, b) =>
                      (a.label || localName(a.uri)).localeCompare(
                        b.label || localName(b.uri),
                      ),
                    cell: (p) => p.label || localName(p.uri),
                  },
                  {
                    id: "domain",
                    header: "Subject class",
                    sortingComparator: (a, b) =>
                      localName(a.domain).localeCompare(localName(b.domain)),
                    cell: (p) => localName(p.domain),
                  },
                  {
                    id: "range",
                    header: "Object class",
                    sortingComparator: (a, b) =>
                      localName(a.range).localeCompare(localName(b.range)),
                    cell: (p) => localName(p.range),
                  },
                ]}
                empty={
                  <Box textAlign="center" color="text-body-secondary">
                    No object-property relationships persisted in the graph.
                  </Box>
                }
              />
            ),
          },
          {
            id: "attributes",
            label: `Attributes (${attributes.length})`,
            content: (
              <SortableTable
                loading={loading}
                items={attributes}
                trackBy="uri"
                variant="embedded"
                defaultSortingColumnId="name"
                columnDefinitions={[
                  {
                    id: "name",
                    header: "Attribute",
                    isRowHeader: true,
                    sortingComparator: (a, b) =>
                      (a.label || localName(a.uri)).localeCompare(
                        b.label || localName(b.uri),
                      ),
                    cell: (p) => p.label || localName(p.uri),
                  },
                  {
                    id: "domain",
                    header: "Class",
                    sortingComparator: (a, b) =>
                      localName(a.domain).localeCompare(localName(b.domain)),
                    cell: (p) => localName(p.domain),
                  },
                  {
                    id: "range",
                    header: "Datatype",
                    sortingComparator: (a, b) =>
                      localName(a.range).localeCompare(localName(b.range)),
                    cell: (p) => localName(p.range),
                  },
                ]}
                empty={
                  <Box textAlign="center" color="text-body-secondary">
                    No datatype-property attributes persisted in the graph.
                  </Box>
                }
              />
            ),
          },
          {
            id: "source",
            label: "Source (Turtle)",
            content: (
              <SpaceBetween size="s">
                {turtleError && (
                  <Alert type="warning" header="Could not load source">
                    {turtleError}
                  </Alert>
                )}
                {turtleLoading ? (
                  <Box textAlign="center" padding="l">
                    <Spinner /> Loading source…
                  </Box>
                ) : turtle ? (
                  <TurtleHighlight>{turtle}</TurtleHighlight>
                ) : (
                  !turtleError && (
                    <Box color="text-body-secondary">
                      No source available for this ontology.
                    </Box>
                  )
                )}
              </SpaceBetween>
            ),
          },
        ]}
      />
    </SpaceBetween>
  );
}
