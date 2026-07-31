// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { useEffect, useState } from "react";

/** A single sample prompt shown on the empty playground. */
export interface ExampleQuestion {
  /** Short chip label. Falls back to `question` when omitted. */
  label?: string;
  /** Full natural-language query sent to the serve layer on click. */
  question: string;
  /** Optional tier hint (e.g. "T1", "T2", "T3") — display only. */
  tier?: string;
  /** Optional execution-path hint (e.g. "jdbc", "athena-federation") — display only. */
  path?: string;
}

interface QuestionsFile {
  questions?: ExampleQuestion[];
}

/**
 * Loads per-namespace sample prompts published to the UI origin at
 * `/questions/{namespaceId}.json` (same CloudFront origin that serves
 * `runtime-config.json`). The file is optional: if it is absent (404) or
 * malformed, this returns an empty list and the playground simply shows no
 * sample prompts.
 */
export function useExampleQuestions(namespaceId: string): ExampleQuestion[] {
  const [questions, setQuestions] = useState<ExampleQuestion[]>([]);

  useEffect(() => {
    if (!namespaceId) {
      setQuestions([]);
      return;
    }
    let cancelled = false;
    fetch(`/questions/${encodeURIComponent(namespaceId)}.json`, {
      headers: { Accept: "application/json" },
    })
      .then((res) => (res.ok ? res.json() : null))
      .then((data: QuestionsFile | null) => {
        if (cancelled || !data || !Array.isArray(data.questions)) {
          if (!cancelled) setQuestions([]);
          return;
        }
        setQuestions(
          data.questions.filter(
            (q): q is ExampleQuestion =>
              typeof q?.question === "string" && q.question.length > 0,
          ),
        );
      })
      .catch(() => {
        if (!cancelled) setQuestions([]);
      });
    return () => {
      cancelled = true;
    };
  }, [namespaceId]);

  return questions;
}
