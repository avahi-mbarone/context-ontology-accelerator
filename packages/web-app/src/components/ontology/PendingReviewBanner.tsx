// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Banner shown when there are pending proposals awaiting review.
 * Appears on the Induced Ontology Detail page and the Graph Search page.
 */
import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import Alert from "@cloudscape-design/components/alert";
import Button from "@cloudscape-design/components/button";
import { listProposals, type Proposal } from "../../services/ontology-engine";
import { useApiClient } from "@components/ApiClientProvider";

export function PendingReviewBanner() {
  const { namespaceId } = useParams<{ namespaceId: string }>();
  const apiClient = useApiClient();
  const navigate = useNavigate();
  const [pending, setPending] = useState<Proposal[]>([]);

  useEffect(() => {
    if (!namespaceId) return;
    let cancelled = false;
    listProposals(apiClient, namespaceId, { status: "pending" })
      .then((items) => {
        if (!cancelled) setPending(items.filter((p) => p.status === "pending"));
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [apiClient, namespaceId]);

  if (pending.length === 0) return null;

  return (
    <Alert
      type="info"
      header={`${pending.length} proposal${pending.length > 1 ? "s" : ""} awaiting review`}
      action={
        <Button
          onClick={() =>
            navigate(
              `/namespaces/${namespaceId}/ontology/proposals/${pending[0].proposal_id}`,
            )
          }
        >
          Review proposal
        </Button>
      }
    >
      New ontology changes have been proposed and are pending your review before
      they are added to the knowledge graph.
    </Alert>
  );
}
