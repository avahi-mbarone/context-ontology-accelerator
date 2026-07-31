// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Session management hooks via HTTP POST to AgentCore /invocations.
 *
 * Session operations (create, list, restore, delete, paginate history) use the
 * same /invocations endpoint as queries, differentiated by the "action" field.
 * This replaces the WebSocket-based session actions from use-session-restore.ts.
 *
 * Mirrors all UX behaviors from the WS hook:
 * - Restore timeout (15s) with delayed spinner (300ms)
 * - Generation counter to reject stale responses on rapid namespace switch
 * - deleteSession auto-fetches next session
 * - createSession updates sessions list
 */
import { useCallback, useEffect, useRef, useState } from "react";
import type { SessionSummary } from "@app-types/playground";
import type { PlaygroundAction } from "./playground-reducer";
import { invokeAgentCore, AuthExpiredError } from "@utils/invoke-agentcore";
import {
  isRecentSessionResponse,
  isSessionHistoryResponse,
  isCreateSessionResponse,
  isListSessionsResponse,
} from "@utils/sse-type-guards";

const RESTORE_TIMEOUT_MS = 15000;
const SPINNER_DELAY_MS = 300;
const ACTION_TIMEOUT_MS = 30000;

export interface UseSessionsOptions {
  /** AgentCore Runtime endpoint URL. */
  queryEndpoint: string | undefined;
  /** OIDC config for token retrieval. */
  oidcConfig: { authority: string; clientId: string } | undefined;
  /** Current namespace ID. */
  namespace: string | undefined;
  /** Dispatch to the playground reducer (for RESTORE_HISTORY, PREPEND_HISTORY). */
  dispatch: (action: PlaygroundAction) => void;
}

export interface UseSessionsReturn {
  /** Active session ID (null if no session yet). */
  sessionId: string | null;
  /** Get the current session ID (for passing to stream hook). */
  getSessionId: () => string | null;
  /** Whether initial session restore is in progress. */
  isRestoring: boolean;
  /** Whether the restore spinner should show (delayed 300ms to avoid flash). */
  showRestoreSpinner: boolean;
  /** Whether restore timed out (show warning). */
  restoreTimedOut: boolean;
  /** Dismiss the restore timeout warning. */
  dismissRestoreWarning: () => void;
  /** List of sessions for the history sidebar. */
  sessions: SessionSummary[];
  /** Whether older history is available for scroll-back. */
  hasMoreHistory: boolean;
  /** Whether older history is currently loading. */
  isLoadingOlderHistory: boolean;
  /** Create a new chat session for the current namespace. */
  createSession: () => Promise<void>;
  /** Load the session list for the current namespace. */
  listSessions: (pageToken?: string) => Promise<void>;
  /** Delete a session by ID. */
  deleteSession: (id: string) => Promise<void>;
  /** Load older messages (scroll-back pagination). */
  loadOlderHistory: () => Promise<void>;
  /** Switch to a different session. */
  switchSession: (id: string) => Promise<void>;
  /** Capture a session ID from a streaming response. */
  captureSessionId: (sid: string) => void;
  /** Reset session state (e.g., on namespace switch). */
  resetSession: () => void;
}

export function useSessions({
  queryEndpoint,
  oidcConfig,
  namespace,
  dispatch,
}: UseSessionsOptions): UseSessionsReturn {
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [isRestoring, setIsRestoring] = useState(true);
  const [showRestoreSpinner, setShowRestoreSpinner] = useState(false);
  const [restoreTimedOut, setRestoreTimedOut] = useState(false);
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [hasMoreHistory, setHasMoreHistory] = useState(false);
  const [isLoadingOlderHistory, setIsLoadingOlderHistory] = useState(false);
  const cursorRef = useRef<number | null>(null);
  const sessionIdRef = useRef<string | null>(null);
  const prevNamespaceRef = useRef<string | undefined>(undefined);
  const generationRef = useRef(0);
  const restoreGenerationRef = useRef(0);
  const restoreTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const spinnerDelayRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const isLoadingOlderRef = useRef(false);
  const abortControllerRef = useRef<AbortController | null>(null);

  useEffect(() => {
    sessionIdRef.current = sessionId;
  }, [sessionId]);

  const clearTimers = useCallback(() => {
    if (restoreTimeoutRef.current) {
      clearTimeout(restoreTimeoutRef.current);
      restoreTimeoutRef.current = null;
    }
    if (spinnerDelayRef.current) {
      clearTimeout(spinnerDelayRef.current);
      spinnerDelayRef.current = null;
    }
  }, []);

  /** Abort all in-flight session actions (on namespace switch or unmount). */
  const abortInflight = useCallback(() => {
    abortControllerRef.current?.abort();
    abortControllerRef.current = null;
  }, []);

  /** POST to /invocations with an action payload.
   * Returns null on errors. Throws AuthExpiredError on 401.
   */
  const invokeAction = useCallback(
    async (actionPayload: Record<string, unknown>): Promise<unknown> => {
      if (!queryEndpoint || !oidcConfig) return null;

      // Create a per-action abort controller linked to the namespace-level one
      const controller = new AbortController();
      abortControllerRef.current = controller;

      try {
        return await invokeAgentCore({
          queryEndpoint,
          oidcConfig,
          payload: actionPayload,
          signal: controller.signal,
          timeoutMs: ACTION_TIMEOUT_MS,
        });
      } catch (err) {
        if (err instanceof AuthExpiredError) throw err;
        return null;
      }
    },
    [queryEndpoint, oidcConfig],
  );

  // ── Restore recent session ──────────────────────────────────────────
  const requestRestore = useCallback(
    async (ns: string) => {
      const currentGen = generationRef.current;
      restoreGenerationRef.current = currentGen;

      clearTimers();
      setIsRestoring(true);
      setShowRestoreSpinner(false);
      setRestoreTimedOut(false);

      // Delayed spinner (avoid flash for fast restores)
      spinnerDelayRef.current = setTimeout(
        () => setShowRestoreSpinner(true),
        SPINNER_DELAY_MS,
      );

      // Timeout warning
      restoreTimeoutRef.current = setTimeout(() => {
        setRestoreTimedOut(true);
        setIsRestoring(false);
        setShowRestoreSpinner(false);
      }, RESTORE_TIMEOUT_MS);

      try {
        const result = await invokeAction({
          action: "getRecentSession",
          namespace: ns,
          profile: {},
        });

        // Stale response guard: ignore if generation changed
        if (restoreGenerationRef.current !== currentGen) return;

        clearTimers();

        if (!isRecentSessionResponse(result)) {
          setIsRestoring(false);
          setShowRestoreSpinner(false);
          return;
        }

        if (result.sessionId) {
          setSessionId(result.sessionId);
          setHasMoreHistory(result.hasMore ?? false);
          cursorRef.current = result.cursor ?? null;

          const messages = result.messages;
          if (messages && messages.length > 0) {
            dispatch({ type: "RESTORE_HISTORY", messages });
          }
        } else {
          setSessionId(null);
          setHasMoreHistory(false);
        }
      } catch {
        // Restore failed silently (including AuthExpired during restore)
        if (restoreGenerationRef.current !== currentGen) return;
        clearTimers();
      } finally {
        if (restoreGenerationRef.current === generationRef.current) {
          setIsRestoring(false);
          setShowRestoreSpinner(false);
        }
      }
    },
    [invokeAction, dispatch, clearTimers],
  );

  // ── Namespace change trigger ────────────────────────────────────────
  useEffect(() => {
    if (!namespace || !queryEndpoint || !oidcConfig) {
      setIsRestoring(false);
      return;
    }

    const isSwitch =
      prevNamespaceRef.current !== undefined &&
      prevNamespaceRef.current !== namespace;

    prevNamespaceRef.current = namespace;

    if (isSwitch) {
      generationRef.current += 1;
      abortInflight();
      clearTimers();
      setSessionId(null);
      setSessions([]);
      setHasMoreHistory(false);
      cursorRef.current = null;
      setRestoreTimedOut(false);
      dispatch({ type: "RESET" });
    }

    void requestRestore(namespace);

    return () => {
      clearTimers();
      abortInflight();
    };
  }, [
    namespace,
    queryEndpoint,
    oidcConfig,
    dispatch,
    clearTimers,
    abortInflight,
    requestRestore,
  ]);

  // ── Session CRUD operations ─────────────────────────────────────────

  const createSession = useCallback(async () => {
    if (!namespace) return;
    try {
      const result = await invokeAction({
        action: "createSession",
        namespace,
        profile: {},
      });
      if (
        isCreateSessionResponse(result) &&
        result.sessionId &&
        !result.error
      ) {
        setSessionId(result.sessionId);
        setHasMoreHistory(false);
        cursorRef.current = null;
        dispatch({ type: "RESET" });
        setSessions((prev) => [
          {
            sessionId: result.sessionId,
            title: "",
            lastActiveAt: new Date().toISOString(),
            messageCount: 0,
            namespaceId: namespace,
          },
          ...prev,
        ]);
      }
    } catch {
      // AuthExpired or other errors handled silently for session ops
    }
  }, [namespace, invokeAction, dispatch]);

  const listSessions = useCallback(
    async (pageToken?: string) => {
      if (!namespace) return;
      try {
        const result = await invokeAction({
          action: "listSessions",
          namespace,
          profile: {},
          ...(pageToken && { pageToken }),
        });
        if (isListSessionsResponse(result) && !result.error) {
          const newSessions = result.sessions ?? [];
          setSessions((prev) =>
            pageToken ? [...prev, ...newSessions] : newSessions,
          );
        }
      } catch {
        // Silent failure for list
      }
    },
    [namespace, invokeAction],
  );

  const deleteSession = useCallback(
    async (id: string) => {
      try {
        const result = await invokeAction({
          action: "deleteSession",
          sessionId: id,
          profile: {},
        });
        // Only update UI if the server confirmed deletion
        if (
          !result ||
          (typeof result === "object" &&
            (result as Record<string, unknown>).error)
        ) {
          return;
        }
        setSessions((prev) => prev.filter((s) => s.sessionId !== id));
        if (sessionIdRef.current === id) {
          setSessionId(null);
          setHasMoreHistory(false);
          cursorRef.current = null;
          dispatch({ type: "RESET" });
          if (namespace) {
            void requestRestore(namespace);
          }
        }
      } catch {
        // Silent failure for delete
      }
    },
    [invokeAction, dispatch, namespace, requestRestore],
  );

  const loadOlderHistory = useCallback(async () => {
    if (
      !sessionIdRef.current ||
      cursorRef.current === null ||
      isLoadingOlderRef.current
    ) {
      return;
    }
    isLoadingOlderRef.current = true;
    setIsLoadingOlderHistory(true);
    try {
      const result = await invokeAction({
        action: "getSessionHistory",
        sessionId: sessionIdRef.current,
        cursor: cursorRef.current,
        limit: 5,
        profile: {},
      });
      if (isSessionHistoryResponse(result) && !result.error) {
        const messages = result.messages ?? [];
        setHasMoreHistory(result.hasMore ?? false);
        cursorRef.current = result.cursor ?? null;
        if (messages.length > 0) {
          dispatch({ type: "PREPEND_HISTORY", messages });
        }
      }
    } catch {
      // Silent failure for pagination
    } finally {
      isLoadingOlderRef.current = false;
      setIsLoadingOlderHistory(false);
    }
  }, [invokeAction, dispatch]);

  const switchSession = useCallback(
    async (id: string) => {
      generationRef.current += 1;
      restoreGenerationRef.current = generationRef.current;
      setSessionId(id);
      setHasMoreHistory(false);
      cursorRef.current = null;
      dispatch({ type: "RESET" });

      try {
        const result = await invokeAction({
          action: "getSessionHistory",
          sessionId: id,
          profile: {},
        });
        if (isSessionHistoryResponse(result) && !result.error) {
          const messages = result.messages ?? [];
          setHasMoreHistory(result.hasMore ?? false);
          cursorRef.current = result.cursor ?? null;
          if (messages.length > 0) {
            dispatch({ type: "RESTORE_HISTORY", messages });
          }
        }
      } catch {
        // Silent failure for switch
      }
    },
    [invokeAction, dispatch],
  );

  const captureSessionId = useCallback((sid: string) => {
    if (!sessionIdRef.current) {
      setSessionId(sid);
    }
  }, []);

  const resetSession = useCallback(() => {
    generationRef.current += 1;
    abortInflight();
    clearTimers();
    setSessionId(null);
    setHasMoreHistory(false);
    cursorRef.current = null;
    setSessions([]);
    setIsRestoring(false);
    setShowRestoreSpinner(false);
    setRestoreTimedOut(false);
  }, [abortInflight, clearTimers]);

  const dismissRestoreWarning = useCallback(() => {
    setRestoreTimedOut(false);
  }, []);

  const getSessionId = useCallback(() => sessionIdRef.current, []);

  return {
    sessionId,
    getSessionId,
    isRestoring,
    showRestoreSpinner,
    restoreTimedOut,
    dismissRestoreWarning,
    sessions,
    hasMoreHistory,
    isLoadingOlderHistory,
    createSession,
    listSessions,
    deleteSession,
    loadOlderHistory,
    switchSession,
    captureSessionId,
    resetSession,
  };
}
