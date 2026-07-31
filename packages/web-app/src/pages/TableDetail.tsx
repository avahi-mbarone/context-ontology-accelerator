// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import React, { useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import Alert from "@cloudscape-design/components/alert";
import AttributeEditor from "@cloudscape-design/components/attribute-editor";
import Badge from "@cloudscape-design/components/badge";
import Box from "@cloudscape-design/components/box";
import Button from "@cloudscape-design/components/button";
import Container from "@cloudscape-design/components/container";
import Flashbar from "@cloudscape-design/components/flashbar";
import FormField from "@cloudscape-design/components/form-field";
import Header from "@cloudscape-design/components/header";
import Icon from "@cloudscape-design/components/icon";
import Input from "@cloudscape-design/components/input";
import KeyValuePairs from "@cloudscape-design/components/key-value-pairs";
import Modal from "@cloudscape-design/components/modal";
import Multiselect from "@cloudscape-design/components/multiselect";
import Pagination from "@cloudscape-design/components/pagination";
import Popover from "@cloudscape-design/components/popover";
import Select from "@cloudscape-design/components/select";
import SpaceBetween from "@cloudscape-design/components/space-between";
import Spinner from "@cloudscape-design/components/spinner";
import StatusIndicator from "@cloudscape-design/components/status-indicator";
import Table from "@cloudscape-design/components/table";
import Textarea from "@cloudscape-design/components/textarea";
import TextFilter from "@cloudscape-design/components/text-filter";
import TokenGroup from "@cloudscape-design/components/token-group";
import type { SelectProps } from "@cloudscape-design/components/select";
import type { TableProps } from "@cloudscape-design/components/table";
import { useCollection } from "@cloudscape-design/collection-hooks";
import {
  useGetSourceTable,
  useGetSource,
  useReviewSourceTable,
  useReviewSourceColumn,
  useUpdateSourceTableMetadata,
  useUpdateSourceColumnMetadata,
  useUpdateSourceTableKeys,
} from "@api-hooks";
import { ReviewStatus, ReviewDecision } from "@coa/control-plane-client";
import type {
  ColumnMetadata,
  ForeignKeyOutput,
} from "@coa/control-plane-client";
import { extractErrorMessage, runSequential } from "@utils";

// --- Constants ---

const PAGE_SIZE = 25;

const REVIEW_STATUS_TYPE: Record<string, "success" | "warning" | "error"> = {
  [ReviewStatus.APPROVED]: "success",
  [ReviewStatus.PENDING_REVIEW]: "warning",
  [ReviewStatus.REJECTED]: "error",
};

const REVIEW_FILTER_OPTIONS: SelectProps.Option[] = [
  { value: "all", label: "All statuses" },
  { value: ReviewStatus.PENDING_REVIEW, label: "Pending review" },
  { value: ReviewStatus.APPROVED, label: "Approved" },
  { value: ReviewStatus.REJECTED, label: "Rejected" },
];

// --- Helpers ---

function getColumnStatus(col: ColumnMetadata): string {
  return col.businessMetadata?.reviewStatus ?? ReviewStatus.PENDING_REVIEW;
}

function statusCell(col: ColumnMetadata) {
  const s = getColumnStatus(col);
  return (
    <StatusIndicator type={REVIEW_STATUS_TYPE[s] ?? "info"}>
      {s === ReviewStatus.PENDING_REVIEW
        ? "Pending review"
        : s === ReviewStatus.APPROVED
          ? "Approved"
          : "Rejected"}
    </StatusIndicator>
  );
}

// --- Confidence / source display (shared) ---

/** Render an AI-inference confidence score as a colour-coded percentage.
 * Deterministic keys carry no score (confidence 0) and render as "—" — the
 * source badge already marks them as authoritative. */
function confidenceCell(confidence?: number) {
  if (typeof confidence !== "number" || confidence <= 0) return "—";
  const pct = Math.round(confidence * 100);
  const type =
    confidence >= 0.8 ? "success" : confidence >= 0.5 ? "warning" : "error";
  return <StatusIndicator type={type}>{pct}%</StatusIndicator>;
}

function sourceBadge(source?: string) {
  return source ? <Badge color="blue">{source}</Badge> : <>—</>;
}

/** Enrichment sources that mean the *description* came from an authoritative
 * record (source catalog, 3rd-party catalog, or a human steward) rather than
 * AI inference. Mirrors `_PROTECTED_DESCRIPTION_SOURCES` in
 * `table_enricher.py`. */
const DESCRIPTION_SOURCE_LABEL: Record<string, string> = {
  DETERMINISTIC: "Source catalog",
  CATALOG_EXISTING: "3rd-party catalog",
  STEWARD_EDITED: "Steward-edited",
  STEWARD_SPECIFIED: "Steward-specified",
  AI_GENERATED: "AI-generated",
};

const NON_AI_DESCRIPTION_SOURCES = new Set([
  "DETERMINISTIC",
  "CATALOG_EXISTING",
  "STEWARD_EDITED",
  "STEWARD_SPECIFIED",
]);

/** Render the description's provenance, plus an inline hint icon when tags/
 * synonyms/glossary terms may be AI-generated even though this description
 * came from a non-AI source. `enrichmentSource` on `businessMetadata` only
 * ever describes the *description* field — tags, synonyms, and glossary
 * terms can be AI-generated independently, so the hint sits directly next
 * to the description-source badge that would otherwise misrepresent them. */
function descriptionSourceBadge(
  meta:
    | {
        enrichmentSource?: string;
        tags?: string[];
        synonyms?: string[];
        glossaryTerms?: string[];
      }
    | undefined,
  metadataEnrichmentEnabled: boolean,
) {
  const source = meta?.enrichmentSource;
  if (!source) return <>—</>;
  return (
    <SpaceBetween direction="horizontal" size="xxs" alignItems="center">
      <Badge color="blue">{DESCRIPTION_SOURCE_LABEL[source] ?? source}</Badge>
      {hasPossiblyAiEnrichedFields(meta, metadataEnrichmentEnabled) && (
        <AiEnrichedHint />
      )}
    </SpaceBetween>
  );
}

/** True when `businessMetadata` has non-empty tags/synonyms/glossary terms
 * that may be AI-generated even though the description's source is
 * non-AI (source catalog, 3rd-party catalog, or steward). The backend
 * stores provenance once per metadata block (see `table_enricher.py`), so
 * this can't be asserted with certainty — it's a hint, not a guarantee.
 *
 * Returns false when `metadataEnrichmentEnabled` is false — the scan
 * pipeline skips the enrichment step entirely for such sources (see
 * `metadataEnrichmentEnabled` on `DatabaseSourceDetail`), so there's no AI
 * involvement to warn about regardless of `enrichmentSource`. */
function hasPossiblyAiEnrichedFields(
  meta:
    | {
        enrichmentSource?: string;
        tags?: string[];
        synonyms?: string[];
        glossaryTerms?: string[];
      }
    | undefined,
  metadataEnrichmentEnabled: boolean,
): boolean {
  if (!metadataEnrichmentEnabled) return false;
  if (!meta?.enrichmentSource) return false;
  if (!NON_AI_DESCRIPTION_SOURCES.has(meta.enrichmentSource)) return false;
  return Boolean(
    meta.tags?.length || meta.synonyms?.length || meta.glossaryTerms?.length,
  );
}

/** Info icon (not a Badge) clarifying that tags/synonyms/glossary terms may
 * be AI-generated even when the description's source is the source catalog,
 * a 3rd-party catalog, or a steward. Rendered inline next to
 * the "Description source" badge (via `descriptionSourceBadge`) since it
 * flags that *that field's* provenance is inconsistent with the provenance
 * of the other metadata fields in the same block. Deliberately visually
 * distinct from the tag/synonym/glossary Badges, so it doesn't read as just
 * another generated tag. */
function AiEnrichedHint() {
  return (
    <Popover
      triggerType="custom"
      size="small"
      dismissButton={false}
      content="This description came from a non-AI source, but tags, synonyms, and glossary terms may still be AI-generated."
    >
      <Icon name="status-info" variant="subtle" ariaLabel="AI-enriched hint" />
    </Popover>
  );
}

const FK_COLUMN_DEFS: TableProps.ColumnDefinition<ForeignKeyOutput>[] = [
  {
    id: "column",
    header: "Column",
    isRowHeader: true,
    cell: (fk) => <Box fontWeight="bold">{fk.column ?? "—"}</Box>,
  },
  {
    id: "references",
    header: "References",
    cell: (fk) =>
      fk.targetColumn
        ? `${fk.targetTable ?? ""}.${fk.targetColumn}`
        : (fk.targetTable ?? "—"),
  },
  { id: "source", header: "Source", cell: (fk) => sourceBadge(fk.source) },
  {
    id: "confidence",
    header: "Confidence",
    cell: (fk) => confidenceCell(fk.confidence),
  },
];

// --- Component ---

export const TableDetail: React.FC = () => {
  const navigate = useNavigate();
  const { namespaceId, dataSourceId, tableId } = useParams<{
    namespaceId: string;
    dataSourceId: string;
    tableId: string;
  }>();
  const { data, isLoading, error, refetch, isFetching } = useGetSourceTable(
    namespaceId ?? "",
    dataSourceId ?? "",
    tableId ?? "",
  );
  // Fetched only to gate the AI-enriched hint icon: when
  // metadataEnrichmentEnabled is false, the scan pipeline never ran the
  // enrichment step, so tags/synonyms/glossary terms can't be AI-generated
  // even if the description's source looks non-AI.
  const { data: sourceData } = useGetSource(
    namespaceId ?? "",
    dataSourceId ?? "",
  );
  const metadataEnrichmentEnabled =
    sourceData?.body?.databaseDetails?.metadataEnrichmentEnabled !== false;
  const reviewTableMutation = useReviewSourceTable(
    namespaceId ?? "",
    dataSourceId ?? "",
    tableId ?? "",
  );
  const reviewColumnMutation = useReviewSourceColumn(
    namespaceId ?? "",
    dataSourceId ?? "",
    tableId ?? "",
  );
  const updateTableMetaMutation = useUpdateSourceTableMetadata(
    namespaceId ?? "",
    dataSourceId ?? "",
    tableId ?? "",
  );
  const updateColumnMetaMutation = useUpdateSourceColumnMetadata(
    namespaceId ?? "",
    dataSourceId ?? "",
    tableId ?? "",
  );
  const updateKeysMutation = useUpdateSourceTableKeys(
    namespaceId ?? "",
    dataSourceId ?? "",
    tableId ?? "",
  );

  const [flash, setFlash] = useState<
    { id: string; type: "success" | "error"; content: string }[]
  >([]);
  const [statusFilter, setStatusFilter] = useState<SelectProps.Option>(
    REVIEW_FILTER_OPTIONS[0]!,
  );
  const [editing, setEditing] = useState<ColumnMetadata | null>(null);
  const [editingTable, setEditingTable] = useState(false);
  const [editingKeys, setEditingKeys] = useState(false);
  const [bulkLoading, setBulkLoading] = useState(false);

  // Filter columns by review status
  const filteredColumns = useMemo(() => {
    const cols = data?.columns ?? [];
    if (!statusFilter.value || statusFilter.value === "all") return cols;
    return cols.filter((c) => getColumnStatus(c) === statusFilter.value);
  }, [data?.columns, statusFilter]);

  // Column definitions matching coa-ui style
  const columnDefs = useMemo<TableProps.ColumnDefinition<ColumnMetadata>[]>(
    () => [
      {
        id: "name",
        header: "Column",
        sortingField: "name",
        isRowHeader: true,
        cell: (col) => <Box fontWeight="bold">{col.name}</Box>,
      },
      {
        id: "dataType",
        header: "Data type",
        sortingField: "dataType",
        cell: (col) => <Box variant="code">{col.dataType}</Box>,
      },
      {
        id: "description",
        header: "Description",
        cell: (col) => col.businessMetadata?.description ?? "—",
        minWidth: 200,
      },
      {
        id: "synonyms",
        header: "Synonyms",
        cell: (col) => {
          const syns = col.businessMetadata?.synonyms;
          return syns && syns.length > 0 ? syns.join(", ") : "—";
        },
      },
      {
        id: "glossaryTerms",
        header: "Glossary",
        cell: (col) => {
          const terms = col.businessMetadata?.glossaryTerms;
          if (!terms || terms.length === 0) return "—";
          return (
            <SpaceBetween direction="horizontal" size="xxs">
              {terms.map((t) => (
                <Badge key={t}>{t}</Badge>
              ))}
            </SpaceBetween>
          );
        },
      },
      {
        id: "tags",
        header: "Tags",
        cell: (col) => {
          const tags = col.businessMetadata?.tags;
          if (!tags || tags.length === 0) return "—";
          return (
            <SpaceBetween direction="horizontal" size="xxs">
              {tags.map((t) => (
                <Badge key={t} color="grey">
                  {t}
                </Badge>
              ))}
            </SpaceBetween>
          );
        },
      },
      {
        id: "distinctValues",
        header: "Sample values",
        cell: (col) => {
          const vals = col.distinctValues;
          if (!vals || vals.length === 0) return "—";
          return (
            <SpaceBetween direction="horizontal" size="xxs">
              {vals.map((v, i) => (
                <Badge key={`${v}-${i}`} color="grey">
                  {v}
                </Badge>
              ))}
            </SpaceBetween>
          );
        },
      },
      {
        id: "nullable",
        header: "Nullable",
        cell: (col) => (col.nullable ? "Yes" : "No"),
      },
      {
        id: "enrichmentSource",
        header: "Description source",
        cell: (col) =>
          descriptionSourceBadge(
            col.businessMetadata,
            metadataEnrichmentEnabled,
          ),
      },
      {
        id: "confidence",
        header: "Confidence",
        cell: (col) => confidenceCell(col.businessMetadata?.confidence),
      },
      {
        id: "status",
        header: "Review status",
        sortingComparator: (a, b) =>
          getColumnStatus(a).localeCompare(getColumnStatus(b)),
        cell: statusCell,
      },
    ],
    [metadataEnrichmentEnabled],
  );

  const { items, collectionProps, filterProps, paginationProps, actions } =
    useCollection(filteredColumns, {
      filtering: {
        empty: (
          <Box textAlign="center" color="text-status-inactive" padding="l">
            No columns found.
          </Box>
        ),
        noMatch: (
          <Box textAlign="center" color="text-status-inactive" padding="l">
            No columns match the filter.
          </Box>
        ),
      },
      pagination: { pageSize: PAGE_SIZE },
      sorting: { defaultState: { sortingColumn: columnDefs[0]! } },
      selection: {},
    });

  if (isLoading) {
    return (
      <Box textAlign="center" padding="xxl">
        <Spinner size="large" />
      </Box>
    );
  }

  if (error) {
    return (
      <Alert type="error" header="Failed to load table">
        {error.message}
      </Alert>
    );
  }

  if (!data) return null;

  const selected = collectionProps.selectedItems ?? [];
  const tableStatus = data.reviewStatus as string;
  const pendingCount = (data.columns ?? []).filter(
    (c) => getColumnStatus(c) === ReviewStatus.PENDING_REVIEW,
  ).length;

  // --- Actions ---

  function notify(type: "success" | "error", content: string) {
    setFlash((prev) => [...prev, { id: String(Date.now()), type, content }]);
  }

  async function handleBulkColumns(decision: ReviewDecision) {
    if (!tableId) return;
    const snapshot = [...selected];
    const total = snapshot.length;
    setBulkLoading(true);
    // Review SEQUENTIALLY, not concurrently. Each per-column review is a full
    // read-modify-write of the entire table asset on the backend (load asset →
    // flip one column → write a new revision). Firing them in parallel makes
    // those writes race off the same baseline revision and clobber each other,
    // so only the last writer's column survives and the rest are silently lost
    // (even though every call returns 200). runSequential awaits each call so
    // the next one reads the revision the previous one just wrote.
    let failed: ColumnMetadata[] = [];
    try {
      ({ failed } = await runSequential(snapshot, (col) =>
        reviewColumnMutation.mutateAsync({ columnName: col.name!, decision }),
      ));
    } finally {
      // Deselect everything that was successfully reviewed; keep only the
      // failed columns selected so the user can retry just those.
      actions.setSelectedItems(failed);
      setBulkLoading(false);
    }

    const verb = decision === ReviewDecision.APPROVED ? "Approved" : "Rejected";
    if (failed.length === 0) {
      notify("success", `${verb} ${total} column${total === 1 ? "" : "s"}.`);
    } else {
      const succeeded = total - failed.length;
      notify(
        "error",
        `${verb} ${succeeded} of ${total} column${total === 1 ? "" : "s"}; ${failed.length} failed.`,
      );
    }
  }

  async function handleApproveAll() {
    if (!tableId) return;
    try {
      await reviewTableMutation.mutateAsync({
        decision: ReviewDecision.APPROVED,
      });
      notify("success", "Table and all columns approved.");
    } catch (e) {
      notify("error", e instanceof Error ? e.message : String(e));
    }
  }

  async function handleRejectTable() {
    if (!tableId) return;
    try {
      await reviewTableMutation.mutateAsync({
        decision: ReviewDecision.REJECTED,
      });
      notify("success", "Table and all columns rejected.");
    } catch (e) {
      notify("error", e instanceof Error ? e.message : String(e));
    }
  }

  function handleSaveEdit(overrides: {
    description: string;
    synonyms: string[];
    glossaryTerms: string[];
    tags: string[];
  }) {
    if (!editing || !tableId) return;
    updateColumnMetaMutation.mutate(
      { columnName: editing.name!, overrides },
      {
        onSuccess: () => {
          notify("success", `Updated column "${editing.name}".`);
          setEditing(null);
        },
        onError: (e) => notify("error", e.message),
      },
    );
  }

  function handleSaveTable(overrides: {
    description: string;
    synonyms: string[];
    glossaryTerms: string[];
    tags: string[];
  }) {
    if (!tableId) return;
    updateTableMetaMutation.mutate(
      { overrides },
      {
        onSuccess: () => {
          notify("success", "Table metadata updated.");
          setEditingTable(false);
        },
        onError: (e) => notify("error", e.message),
      },
    );
  }

  function handleSaveKeys(payload: {
    primaryKey: { columns: string[] };
    foreignKeys: {
      column: string;
      targetTable: string;
      targetColumn?: string;
    }[];
  }) {
    if (!tableId) return;
    updateKeysMutation.mutate(payload, {
      onSuccess: () => {
        notify("success", "Keys & relationships updated.");
        setEditingKeys(false);
      },
    });
  }

  return (
    <SpaceBetween size="m">
      {flash.length > 0 && (
        <Flashbar
          items={flash.map((f) => ({
            ...f,
            dismissible: true,
            onDismiss: () =>
              setFlash((prev) => prev.filter((x) => x.id !== f.id)),
          }))}
        />
      )}

      {/* Table-level metadata header */}
      <Header
        variant="h1"
        actions={
          <SpaceBetween direction="horizontal" size="xs">
            <Button
              iconName="refresh"
              loading={isFetching}
              onClick={() => refetch()}
            >
              Refresh
            </Button>
            <Button onClick={() => navigate(-1)}>Back</Button>
            <Button
              onClick={handleRejectTable}
              loading={reviewTableMutation.isPending}
              disabled={tableStatus === ReviewStatus.REJECTED}
            >
              Reject table &amp; all columns
            </Button>
            <Button
              variant="primary"
              onClick={handleApproveAll}
              loading={reviewTableMutation.isPending}
              disabled={tableStatus === ReviewStatus.APPROVED}
            >
              Approve table &amp; all columns
            </Button>
          </SpaceBetween>
        }
      >
        {data.name} <Badge color="grey">{data.database}</Badge>
      </Header>

      {/* Table metadata summary */}
      <Container
        header={
          <Header
            variant="h2"
            actions={
              <Button onClick={() => setEditingTable(true)}>Edit</Button>
            }
          >
            Table metadata
          </Header>
        }
      >
        <KeyValuePairs
          columns={3}
          items={[
            { label: "Table ID", value: data.tableId },
            {
              label: "Review status",
              value: (
                <StatusIndicator
                  type={REVIEW_STATUS_TYPE[tableStatus] ?? "info"}
                >
                  {tableStatus === ReviewStatus.PENDING_REVIEW
                    ? "Pending review"
                    : tableStatus}
                </StatusIndicator>
              ),
            },
            {
              label: "Description source",
              value: descriptionSourceBadge(
                data.businessMetadata,
                metadataEnrichmentEnabled,
              ),
            },
            {
              label: "Description",
              value: data.businessMetadata?.description ?? "—",
            },
            {
              label: "Synonyms",
              value: data.businessMetadata?.synonyms?.join(", ") || "—",
            },
            {
              label: "Tags",
              value: data.businessMetadata?.tags?.join(", ") || "—",
            },
            {
              label: "Glossary terms",
              value: data.businessMetadata?.glossaryTerms?.join(", ") || "—",
            },
            { label: "Format", value: data.technicalMetadata?.format || "—" },
            {
              label: "Location",
              value: data.technicalMetadata?.location || "—",
            },
          ]}
        />
      </Container>

      {/* Keys & relationships */}
      <Container
        header={
          <Header
            variant="h2"
            actions={
              <Button
                onClick={() => {
                  updateKeysMutation.reset();
                  setEditingKeys(true);
                }}
              >
                Edit keys
              </Button>
            }
          >
            Keys &amp; relationships
          </Header>
        }
      >
        <SpaceBetween size="l">
          <KeyValuePairs
            columns={3}
            items={[
              {
                label: "Primary key",
                value:
                  data.primaryKey?.columns && data.primaryKey.columns.length > 0
                    ? data.primaryKey.columns.join(", ")
                    : "—",
              },
              { label: "Source", value: sourceBadge(data.primaryKey?.source) },
              {
                label: "Confidence",
                value: confidenceCell(data.primaryKey?.confidence),
              },
            ]}
          />
          <Table<ForeignKeyOutput>
            variant="embedded"
            items={data.foreignKeys ?? []}
            trackBy="column"
            columnDefinitions={FK_COLUMN_DEFS}
            header={
              <Header
                variant="h3"
                counter={`(${data.foreignKeys?.length ?? 0})`}
              >
                Foreign keys
              </Header>
            }
            empty={
              <Box textAlign="center" color="text-status-inactive" padding="s">
                No foreign key relationships detected.
              </Box>
            }
          />
        </SpaceBetween>
      </Container>

      {/* Pending review alert */}
      {pendingCount > 0 && (
        <Alert
          type="info"
          header={`${pendingCount} column${pendingCount === 1 ? "" : "s"} pending review`}
        >
          AI enrichment produced descriptions, synonyms, and glossary mappings
          for these columns. Review or edit them before approving.
        </Alert>
      )}

      {/* Columns table with selection, filtering, pagination, edit */}
      <Table<ColumnMetadata>
        {...collectionProps}
        items={items}
        trackBy="name"
        variant="container"
        stickyHeader
        resizableColumns
        selectionType="multi"
        columnDefinitions={columnDefs}
        header={
          <Header
            variant="h2"
            counter={`(${filteredColumns.length})`}
            actions={
              <SpaceBetween direction="horizontal" size="xs">
                <Button
                  disabled={selected.length === 0 || bulkLoading}
                  loading={bulkLoading}
                  onClick={() => handleBulkColumns(ReviewDecision.REJECTED)}
                >
                  Reject selected
                </Button>
                <Button
                  disabled={selected.length === 0 || bulkLoading}
                  loading={bulkLoading}
                  onClick={() => handleBulkColumns(ReviewDecision.APPROVED)}
                >
                  Approve selected
                </Button>
                <Button
                  disabled={selected.length !== 1 || bulkLoading}
                  onClick={() => setEditing(selected[0] ?? null)}
                >
                  Edit
                </Button>
              </SpaceBetween>
            }
          >
            Columns
          </Header>
        }
        filter={
          <SpaceBetween direction="horizontal" size="s">
            <TextFilter
              {...filterProps}
              filteringPlaceholder="Find columns"
              filteringAriaLabel="Filter columns"
            />
            <Select
              selectedOption={statusFilter}
              onChange={({ detail }) => setStatusFilter(detail.selectedOption)}
              options={REVIEW_FILTER_OPTIONS}
              ariaLabel="Filter by review status"
            />
          </SpaceBetween>
        }
        pagination={<Pagination {...paginationProps} />}
        empty={
          <Box textAlign="center" color="text-status-inactive" padding="l">
            No columns discovered yet.
          </Box>
        }
        ariaLabels={{
          tableLabel: "Column metadata",
          selectionGroupLabel: "Column selection",
          allItemsSelectionLabel: ({ selectedItems }) =>
            `${selectedItems.length} columns selected`,
          itemSelectionLabel: (_s, row) => `Select ${row.name}`,
        }}
      />

      {/* Edit modal */}
      {editing && (
        <EditColumnModal
          column={editing}
          onDismiss={() => setEditing(null)}
          onSave={handleSaveEdit}
          loading={updateColumnMetaMutation.isPending}
        />
      )}

      {/* Table edit modal */}
      {editingTable && (
        <EditTableModal
          businessMetadata={data.businessMetadata}
          tableName={data.name ?? ""}
          onDismiss={() => setEditingTable(false)}
          onSave={handleSaveTable}
          loading={updateTableMetaMutation.isPending}
        />
      )}

      {/* Keys edit modal */}
      {editingKeys && (
        <EditKeysModal
          tableName={data.name ?? ""}
          columnNames={(data.columns ?? []).map((c) => c.name!)}
          primaryKey={data.primaryKey?.columns ?? []}
          foreignKeys={data.foreignKeys ?? []}
          onDismiss={() => setEditingKeys(false)}
          onSave={handleSaveKeys}
          loading={updateKeysMutation.isPending}
          error={updateKeysMutation.error}
        />
      )}
    </SpaceBetween>
  );
};

// --- Shared helpers ---

function toTokens(values: string[]): { label: string; dismissLabel: string }[] {
  return values.map((v) => ({ label: v, dismissLabel: `Remove ${v}` }));
}

function useTokenField(initial: string[]) {
  const [items, setItems] = useState(toTokens(initial));
  const [input, setInput] = useState("");

  function add() {
    const trimmed = input.trim();
    if (trimmed && !items.some((t) => t.label === trimmed)) {
      setItems([
        ...items,
        { label: trimmed, dismissLabel: `Remove ${trimmed}` },
      ]);
    }
    setInput("");
  }

  function remove(index: number) {
    setItems(items.filter((_, i) => i !== index));
  }

  return {
    items,
    input,
    setInput,
    add,
    remove,
    values: items.map((t) => t.label),
  };
}

// --- Edit Table Modal ---

function EditTableModal({
  businessMetadata,
  tableName,
  onDismiss,
  onSave,
  loading,
}: {
  businessMetadata?: {
    description?: string;
    synonyms?: string[];
    glossaryTerms?: string[];
    tags?: string[];
  };
  tableName: string;
  onDismiss: () => void;
  onSave: (overrides: {
    description: string;
    synonyms: string[];
    glossaryTerms: string[];
    tags: string[];
  }) => void;
  loading: boolean;
}) {
  const bm = businessMetadata;
  const [description, setDescription] = useState(bm?.description ?? "");
  const synonyms = useTokenField(bm?.synonyms ?? []);
  const glossary = useTokenField(bm?.glossaryTerms ?? []);
  const tags = useTokenField(bm?.tags ?? []);

  return (
    <Modal
      visible
      size="large"
      onDismiss={onDismiss}
      header={`Edit table: ${tableName}`}
      footer={
        <Box float="right">
          <SpaceBetween direction="horizontal" size="xs">
            <Button variant="link" onClick={onDismiss}>
              Cancel
            </Button>
            <Button
              variant="primary"
              loading={loading}
              onClick={() =>
                onSave({
                  description,
                  synonyms: synonyms.values,
                  glossaryTerms: glossary.values,
                  tags: tags.values,
                })
              }
            >
              Save
            </Button>
          </SpaceBetween>
        </Box>
      }
    >
      <SpaceBetween size="m">
        <FormField label="Description">
          <Textarea
            value={description}
            onChange={({ detail }) => setDescription(detail.value)}
            rows={3}
          />
        </FormField>
        <FormField label="Synonyms" description="Press Enter to add.">
          <SpaceBetween size="xs">
            <Input
              value={synonyms.input}
              onChange={({ detail }) => synonyms.setInput(detail.value)}
              onKeyDown={({ detail }) => {
                if (detail.key === "Enter") synonyms.add();
              }}
              placeholder="e.g. customers_table"
            />
            <TokenGroup
              items={synonyms.items}
              onDismiss={({ detail }) => synonyms.remove(detail.itemIndex)}
            />
          </SpaceBetween>
        </FormField>
        <FormField label="Glossary terms" description="Press Enter to add.">
          <SpaceBetween size="xs">
            <Input
              value={glossary.input}
              onChange={({ detail }) => glossary.setInput(detail.value)}
              onKeyDown={({ detail }) => {
                if (detail.key === "Enter") glossary.add();
              }}
              placeholder="e.g. Customer"
            />
            <TokenGroup
              items={glossary.items}
              onDismiss={({ detail }) => glossary.remove(detail.itemIndex)}
            />
          </SpaceBetween>
        </FormField>
        <FormField label="Tags" description="Press Enter to add.">
          <SpaceBetween size="xs">
            <Input
              value={tags.input}
              onChange={({ detail }) => tags.setInput(detail.value)}
              onKeyDown={({ detail }) => {
                if (detail.key === "Enter") tags.add();
              }}
              placeholder="e.g. pii"
            />
            <TokenGroup
              items={tags.items}
              onDismiss={({ detail }) => tags.remove(detail.itemIndex)}
            />
          </SpaceBetween>
        </FormField>
      </SpaceBetween>
    </Modal>
  );
}

// --- Edit Column Modal ---

function EditColumnModal({
  column,
  onDismiss,
  onSave,
  loading,
}: {
  column: ColumnMetadata;
  onDismiss: () => void;
  onSave: (overrides: {
    description: string;
    synonyms: string[];
    glossaryTerms: string[];
    tags: string[];
  }) => void;
  loading: boolean;
}) {
  const bm = column.businessMetadata;
  const [description, setDescription] = useState(bm?.description ?? "");
  const synonyms = useTokenField(bm?.synonyms ?? []);
  const glossary = useTokenField(bm?.glossaryTerms ?? []);
  const tags = useTokenField(bm?.tags ?? []);

  return (
    <Modal
      visible
      size="large"
      onDismiss={onDismiss}
      header={`Edit column: ${column.name}`}
      footer={
        <Box float="right">
          <SpaceBetween direction="horizontal" size="xs">
            <Button variant="link" onClick={onDismiss}>
              Cancel
            </Button>
            <Button
              variant="primary"
              loading={loading}
              onClick={() =>
                onSave({
                  description,
                  synonyms: synonyms.values,
                  glossaryTerms: glossary.values,
                  tags: tags.values,
                })
              }
            >
              Save &amp; approve
            </Button>
          </SpaceBetween>
        </Box>
      }
    >
      <SpaceBetween size="m">
        <FormField label="Data type">
          <Input value={column.dataType ?? ""} disabled />
        </FormField>
        <FormField label="Description">
          <Textarea
            value={description}
            onChange={({ detail }) => setDescription(detail.value)}
            rows={3}
          />
        </FormField>
        <FormField label="Synonyms" description="Press Enter to add.">
          <SpaceBetween size="xs">
            <Input
              value={synonyms.input}
              onChange={({ detail }) => synonyms.setInput(detail.value)}
              onKeyDown={({ detail }) => {
                if (detail.key === "Enter") synonyms.add();
              }}
              placeholder="e.g. customer_id"
            />
            <TokenGroup
              items={synonyms.items}
              onDismiss={({ detail }) => synonyms.remove(detail.itemIndex)}
            />
          </SpaceBetween>
        </FormField>
        <FormField label="Glossary terms" description="Press Enter to add.">
          <SpaceBetween size="xs">
            <Input
              value={glossary.input}
              onChange={({ detail }) => glossary.setInput(detail.value)}
              onKeyDown={({ detail }) => {
                if (detail.key === "Enter") glossary.add();
              }}
              placeholder="e.g. Customer"
            />
            <TokenGroup
              items={glossary.items}
              onDismiss={({ detail }) => glossary.remove(detail.itemIndex)}
            />
          </SpaceBetween>
        </FormField>
        <FormField label="Tags" description="Press Enter to add.">
          <SpaceBetween size="xs">
            <Input
              value={tags.input}
              onChange={({ detail }) => tags.setInput(detail.value)}
              onKeyDown={({ detail }) => {
                if (detail.key === "Enter") tags.add();
              }}
              placeholder="e.g. pii"
            />
            <TokenGroup
              items={tags.items}
              onDismiss={({ detail }) => tags.remove(detail.itemIndex)}
            />
          </SpaceBetween>
        </FormField>
      </SpaceBetween>
    </Modal>
  );
}

// --- Edit Keys Modal ---

function EditKeysModal({
  tableName,
  columnNames,
  primaryKey,
  foreignKeys,
  onDismiss,
  onSave,
  loading,
  error,
}: {
  tableName: string;
  columnNames: string[];
  primaryKey: string[];
  foreignKeys: ForeignKeyOutput[];
  onDismiss: () => void;
  onSave: (payload: {
    primaryKey: { columns: string[] };
    foreignKeys: {
      column: string;
      targetTable: string;
      targetColumn?: string;
    }[];
  }) => void;
  loading: boolean;
  error?: Error | null;
}) {
  const columnOptions = columnNames.map((c) => ({ label: c, value: c }));
  const [pkSelected, setPkSelected] = useState<readonly SelectProps.Option[]>(
    primaryKey.map((c) => ({ label: c, value: c })),
  );
  const [fkRows, setFkRows] = useState(
    foreignKeys.map((fk) => ({
      column: fk.column ?? "",
      targetTable: fk.targetTable ?? "",
      targetColumn: fk.targetColumn ?? "",
    })),
  );

  function updateRow(index: number, patch: Partial<(typeof fkRows)[number]>) {
    setFkRows(fkRows.map((r, i) => (i === index ? { ...r, ...patch } : r)));
  }

  return (
    <Modal
      visible
      size="large"
      onDismiss={onDismiss}
      header={`Edit keys: ${tableName}`}
      footer={
        <Box float="right">
          <SpaceBetween direction="horizontal" size="xs">
            <Button variant="link" onClick={onDismiss}>
              Cancel
            </Button>
            <Button
              variant="primary"
              loading={loading}
              onClick={() =>
                onSave({
                  primaryKey: {
                    columns: pkSelected
                      .map((o) => o.value ?? "")
                      .filter(Boolean),
                  },
                  foreignKeys: fkRows
                    .filter((r) => r.column && r.targetTable)
                    .map((r) => ({
                      column: r.column,
                      targetTable: r.targetTable,
                      targetColumn: r.targetColumn || undefined,
                    })),
                })
              }
            >
              Save
            </Button>
          </SpaceBetween>
        </Box>
      }
    >
      <SpaceBetween size="l">
        {error && (
          <Alert type="error" header="Failed to save keys">
            {extractErrorMessage(error)}
          </Alert>
        )}
        <FormField
          label="Primary key columns"
          description="Steward-specified keys override discovered ones."
        >
          <Multiselect
            selectedOptions={pkSelected}
            onChange={({ detail }) => setPkSelected(detail.selectedOptions)}
            options={columnOptions}
            placeholder="Select primary key columns"
          />
        </FormField>
        <AttributeEditor
          items={fkRows}
          addButtonText="Add foreign key"
          removeButtonText="Remove"
          empty="No foreign keys."
          onAddButtonClick={() =>
            setFkRows([
              ...fkRows,
              { column: "", targetTable: "", targetColumn: "" },
            ])
          }
          onRemoveButtonClick={({ detail }) =>
            setFkRows(fkRows.filter((_, i) => i !== detail.itemIndex))
          }
          definition={[
            {
              label: "Column",
              control: (item, i) => (
                <Input
                  value={item.column}
                  onChange={({ detail }) =>
                    updateRow(i, { column: detail.value })
                  }
                  placeholder="customer_id"
                />
              ),
            },
            {
              label: "Target table",
              control: (item, i) => (
                <Input
                  value={item.targetTable}
                  onChange={({ detail }) =>
                    updateRow(i, { targetTable: detail.value })
                  }
                  placeholder="customers"
                />
              ),
            },
            {
              label: "Target column",
              control: (item, i) => (
                <Input
                  value={item.targetColumn}
                  onChange={({ detail }) =>
                    updateRow(i, { targetColumn: detail.value })
                  }
                  placeholder="id"
                />
              ),
            },
          ]}
        />
      </SpaceBetween>
    </Modal>
  );
}
