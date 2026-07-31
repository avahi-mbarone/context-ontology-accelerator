// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * OntologyInventoryView — the Explorer's "what ontologies exist here" table.
 *
 * Covers every registered ontology in the namespace (induced, foundational, and
 * uploaded) with a type filter, so the Explorer is the single inventory of the
 * namespace's graph. Read-only: loading/uploading and grounding-input curation
 * stay on the Induction page, which owns those actions.
 */
import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import Alert from "@cloudscape-design/components/alert";
import Badge from "@cloudscape-design/components/badge";
import Box from "@cloudscape-design/components/box";
import Button from "@cloudscape-design/components/button";
import Header from "@cloudscape-design/components/header";
import Link from "@cloudscape-design/components/link";
import SegmentedControl from "@cloudscape-design/components/segmented-control";
import SpaceBetween from "@cloudscape-design/components/space-between";
import StatusIndicator from "@cloudscape-design/components/status-indicator";
import { SortableTable } from "@components/SortableTable";
import type { ApiClient } from "@components/ApiClientProvider";
import { formatTimestamp } from "@utils/helpers";
import {
  listOntologies,
  type OntologyRecord,
} from "../../../services/ontology-engine";
import { ontologyTypeDisplay, ontologyTypeGroup } from "../../OntologyPage";

type TypeFilter = "all" | "induced" | "foundational" | "uploaded";

export function OntologyInventoryView({
  apiClient,
  namespace,
}: {
  apiClient: ApiClient;
  namespace?: string;
}) {
  const navigate = useNavigate();
  const [items, setItems] = useState<OntologyRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);
  const [typeFilter, setTypeFilter] = useState<TypeFilter>("all");

  useEffect(() => {
    if (!namespace) return;
    setLoading(true);
    setError(null);
    listOntologies(apiClient, namespace)
      .then(setItems)
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false));
  }, [apiClient, namespace, refreshKey]);

  const counts = useMemo(() => {
    const c = { induced: 0, foundational: 0, uploaded: 0 };
    for (const o of items) {
      const g = ontologyTypeGroup(o.ontology_type);
      if (g === "induced" || g === "foundational" || g === "uploaded")
        c[g] += 1;
    }
    return c;
  }, [items]);

  const visible = useMemo(
    () =>
      typeFilter === "all"
        ? items
        : items.filter(
            (o) => ontologyTypeGroup(o.ontology_type) === typeFilter,
          ),
    [items, typeFilter],
  );

  return (
    <SpaceBetween size="s">
      {error && (
        <Alert
          type="warning"
          dismissible
          onDismiss={() => setError(null)}
          header="Could not load ontologies"
        >
          {error}
        </Alert>
      )}
      <SortableTable
        loading={loading}
        items={visible}
        trackBy="ontology_id"
        defaultSortingColumnId="title"
        columnDefinitions={[
          {
            id: "title",
            header: "Ontology",
            isRowHeader: true,
            sortingComparator: (a, b) =>
              (a.title || a.ontology_id).localeCompare(
                b.title || b.ontology_id,
              ),
            cell: (o) => {
              // Only induced ontologies have a browsable graph-contents page.
              const href =
                ontologyTypeGroup(o.ontology_type) === "induced"
                  ? `/namespaces/${namespace}/ontology/induced?ontology_id=${encodeURIComponent(
                      o.ontology_id,
                    )}`
                  : null;
              return (
                <SpaceBetween size="xxxs">
                  {href ? (
                    <Link
                      href={href}
                      onFollow={(ev) => {
                        ev.preventDefault();
                        navigate(href);
                      }}
                    >
                      {o.title || o.ontology_id}
                    </Link>
                  ) : (
                    <Box>{o.title || o.ontology_id}</Box>
                  )}
                  <Box variant="small" color="text-status-inactive">
                    {o.uri}
                  </Box>
                </SpaceBetween>
              );
            },
          },
          {
            id: "type",
            header: "Type",
            sortingComparator: (a, b) =>
              ontologyTypeGroup(a.ontology_type).localeCompare(
                ontologyTypeGroup(b.ontology_type),
              ),
            cell: (o) => {
              const { label, color } = ontologyTypeDisplay(o.ontology_type);
              return o.status === "deleting" ? (
                <StatusIndicator type="in-progress">
                  Delete in progress
                </StatusIndicator>
              ) : (
                <Badge color={color}>{label}</Badge>
              );
            },
          },
          {
            id: "classes",
            header: "Classes",
            sortingComparator: (a, b) =>
              (a.class_count ?? 0) - (b.class_count ?? 0),
            cell: (o) => o.class_count ?? 0,
          },
          {
            id: "properties",
            header: "Properties",
            sortingComparator: (a, b) =>
              (a.property_count ?? 0) - (b.property_count ?? 0),
            cell: (o) => o.property_count ?? 0,
          },
          {
            id: "axioms",
            header: "Axioms",
            sortingComparator: (a, b) =>
              (a.axiom_count ?? 0) - (b.axiom_count ?? 0),
            cell: (o) => o.axiom_count ?? 0,
          },
          {
            id: "created",
            header: "Created",
            sortingComparator: (a, b) =>
              (a.created_at ?? "").localeCompare(b.created_at ?? ""),
            cell: (o) => formatTimestamp(o.created_at),
          },
        ]}
        empty={
          <Box textAlign="center" color="text-status-inactive" padding="l">
            {typeFilter === "all"
              ? "No ontologies yet. Run an induction, or load a reference ontology from the Induction page."
              : "No ontologies of this type."}
          </Box>
        }
        header={
          <Header
            counter={`(${visible.length})`}
            description="Every ontology registered in this namespace. Open an induced ontology to browse its classes and relationships."
            actions={
              <SpaceBetween direction="horizontal" size="xs">
                <SegmentedControl
                  selectedId={typeFilter}
                  onChange={({ detail }) => {
                    const id = detail.selectedId;
                    if (
                      id === "all" ||
                      id === "induced" ||
                      id === "foundational" ||
                      id === "uploaded"
                    ) {
                      setTypeFilter(id);
                    }
                  }}
                  label="Filter by ontology type"
                  options={[
                    { id: "all", text: `All (${items.length})` },
                    { id: "induced", text: `Induced (${counts.induced})` },
                    {
                      id: "foundational",
                      text: `Foundational (${counts.foundational})`,
                    },
                    { id: "uploaded", text: `Uploaded (${counts.uploaded})` },
                  ]}
                />
                <Button
                  iconName="refresh"
                  loading={loading}
                  onClick={() => setRefreshKey((k) => k + 1)}
                >
                  Refresh
                </Button>
              </SpaceBetween>
            }
          >
            Ontologies
          </Header>
        }
      />
    </SpaceBetween>
  );
}
