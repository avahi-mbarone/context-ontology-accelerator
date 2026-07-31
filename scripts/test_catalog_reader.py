# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Integration test: read_approved_catalog against a deployed stack.

Usage:
    export SMUS_DOMAIN_ID=<your-domain-id>
    export DATAZONE_PROJECT_ID=<your-project-id>
    export DATASOURCES_TABLE=<your-datasources-table-name>
    export AWS_REGION=us-east-1

    uv run python scripts/test_catalog_reader.py <namespace-id> <ds-id-1> [ds-id-2 ...]
"""

import json
import os
import sys

from coa_common.metadata_store.catalog_reader import read_approved_catalog


def main():
    if len(sys.argv) < 3:
        print(f"Usage: {sys.argv[0]} <namespace-id> <data-source-id> [data-source-id ...]")
        sys.exit(1)

    namespace_id = sys.argv[1]
    data_source_ids = sys.argv[2:]

    required_env = ["SMUS_DOMAIN_ID", "DATAZONE_PROJECT_ID", "DATASOURCES_TABLE"]
    missing = [v for v in required_env if not os.environ.get(v)]
    if missing:
        print(f"Missing environment variables: {', '.join(missing)}")
        sys.exit(1)

    result = read_approved_catalog(
        domain_id=os.environ["SMUS_DOMAIN_ID"],
        project_id=os.environ["DATAZONE_PROJECT_ID"],
        namespace_id=namespace_id,
        data_source_ids=data_source_ids,
        datasources_table=os.environ["DATASOURCES_TABLE"],
        region=os.environ.get("AWS_REGION", "us-east-1"),
    )

    print(json.dumps(result, indent=2))
    print(
        f"\n--- Summary: {len(result['sources'])} sources, "
        f"{sum(len(db['tables']) for s in result['sources'] for db in s['databases'])} approved tables"
    )


if __name__ == "__main__":
    main()
