// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { useInfiniteQuery } from "@tanstack/react-query";
import { useApiClient } from "@components/ApiClientProvider";
import {
  searchEntitiesPaged,
  type GraphSearchResult,
} from "../services/ontology-engine";

/**
 * How many classes each backend fetch pulls. The List view displays a smaller
 * slice per page (see {@link CLASS_DISPLAY_PAGE_SIZE}) and only triggers the
 * next backend fetch when the user pages into not-yet-loaded territory — so a
 * multi-thousand-class namespace stays a handful of round-trips, not one per
 * displayed page. Matches the original wildcard fetch size.
 */
export const CLASS_FETCH_CHUNK_SIZE = 100;

/** How many classes the List view shows per Cloudscape page. */
export const CLASS_DISPLAY_PAGE_SIZE = 20;

/**
 * Paginated class listing for the Ontology Explorer, backed by the graph-search
 * endpoint's ``{hits, total_count}`` envelope. Fetches classes in chunks of
 * {@link CLASS_FETCH_CHUNK_SIZE} via ``useInfiniteQuery``; ``total_count`` (the
 * same on every page) lets the caller render a known Cloudscape page count.
 *
 * The empty/whitespace query is sent to the backend as ``*`` (its match-all
 * wildcard), so the default view lists every class in the namespace — pageable
 * in full, not capped at one chunk. A non-empty query pages across all matches.
 *
 * When ``ontologyId`` is set, results are restricted to that ontology's named
 * graph (the backend ``ontology_id`` filter); when undefined, all ontologies in
 * the namespace are searched. The ontology id is part of the query key, so
 * switching ontologies fetches (and caches) an independent paged result set.
 *
 * `getNextPageParam` advances the offset by the number of hits actually
 * returned and stops as soon as a chunk comes back short — the backend returns
 * exactly ``min(limit, remaining)`` distinct classes, so a short chunk means
 * the end of the result set.
 *
 * Pass ``enabled: false`` to hold the query off entirely (in addition to the
 * namespace-id guard). The Explorer uses this so the Graph view doesn't spend a
 * class-chunk fetch plus a full-namespace COUNT it never renders.
 */
export function useGraphClasses(
  namespaceId: string | undefined,
  query: string,
  ontologyId?: string,
  enabled = true,
) {
  const apiClient = useApiClient();
  const q = query.trim() || "*";

  return useInfiniteQuery<GraphSearchResult, Error>({
    queryKey: ["graph-classes", namespaceId, q, ontologyId ?? null],
    enabled: Boolean(namespaceId) && enabled,
    queryFn: async ({ pageParam }) => {
      const offset = (pageParam as number) ?? 0;
      return searchEntitiesPaged(apiClient, namespaceId!, q, {
        kind: "class",
        ontology_id: ontologyId,
        limit: CLASS_FETCH_CHUNK_SIZE,
        offset,
      });
    },
    initialPageParam: 0,
    getNextPageParam: (lastPage, allPages) => {
      // Short chunk → no more results. Otherwise the next offset is the total
      // number of hits fetched so far.
      if (lastPage.hits.length < CLASS_FETCH_CHUNK_SIZE) return undefined;
      const loaded = allPages.reduce((n, p) => n + p.hits.length, 0);
      return loaded < lastPage.total_count ? loaded : undefined;
    },
  });
}
