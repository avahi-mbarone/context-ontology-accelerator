// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Hook to fetch session history for a given sessionId via REST/SSE.
 * Returns the matched HistoryMessage for a requestId, plus loading/error state.
 *
 * Uses the shared invokeAgentCore utility for token + SSE parsing.
 */
import { useCallback, useContext, useEffect, useRef, useState } from "react";
import type { HistoryMessage } from "@app-types/playground";
import { RuntimeConfigContext } from "@components/RuntimeContext";
import { buildQueryEndpoint } from "@utils/build-query-endpoint";
import { invokeAgentCore } from "@utils/invoke-agentcore";
import { isSessionHistoryResponse } from "@utils/sse-type-guards";

export interface SessionHistoryResult {
  message: HistoryMessage | null;
  userQuery: string;
}

export interface UseSessionHistoryReturn {
  data: SessionHistoryResult | null;
  loading: boolean;
  error: string | null;
  retry: () => void;
}

export function useSessionHistory(
  sessionId: string | undefined,
  requestId: string | undefined,
): UseSessionHistoryReturn {
  const runtimeContext = useContext(RuntimeConfigContext);
  const [data, setData] = useState<SessionHistoryResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const hasFetched = useRef(false);

  const queryEndpoint = buildQueryEndpoint(runtimeContext);

  const fetchHistory = useCallback(async () => {
    if (!sessionId || !requestId) {
      setError("Missing session or request ID.");
      return;
    }
    if (!queryEndpoint || !runtimeContext?.oidcConfig) {
      setError("Query endpoint not configured.");
      return;
    }

    setLoading(true);
    setError(null);

    try {
      const result = await invokeAgentCore({
        queryEndpoint,
        oidcConfig: runtimeContext.oidcConfig,
        payload: {
          action: "getSessionHistory",
          sessionId,
          profile: {},
        },
        timeoutMs: 30000,
      });

      if (!isSessionHistoryResponse(result)) {
        setError("Invalid session history response.");
        setLoading(false);
        return;
      }

      if (result.error) {
        setError(
          typeof result.message === "string"
            ? result.message
            : "Failed to load session history.",
        );
        setLoading(false);
        return;
      }

      const messages = result.messages;
      let userQuery = "\u2014";
      let matched: HistoryMessage | undefined;

      for (let i = 0; i < messages.length; i++) {
        const m = messages[i];
        if (m.role === "assistant" && m.metadata?.requestId === requestId) {
          matched = m;
          if (i > 0 && messages[i - 1].role === "user") {
            userQuery = messages[i - 1].content;
          }
          break;
        }
      }

      if (matched) {
        setData({ message: matched, userQuery });
      } else {
        setError(
          `Request ${requestId} not found in session history. It may have expired.`,
        );
      }
      setLoading(false);
    } catch {
      setError("Failed to load session history.");
      setLoading(false);
    }
  }, [sessionId, requestId, queryEndpoint, runtimeContext]);

  useEffect(() => {
    if (!data && !hasFetched.current) {
      hasFetched.current = true;
      fetchHistory();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const retry = useCallback(() => {
    hasFetched.current = false;
    setData(null);
    setError(null);
    fetchHistory();
  }, [fetchHistory]);

  return { data, loading, error, retry };
}
