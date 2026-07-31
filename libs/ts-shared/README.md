# libs/ts-shared

Shared TypeScript types and enums for the Context Ontology Accelerator. These definitions mirror `libs/common` (Python) to ensure cross-language type safety.

## Usage

```typescript
import { PrincipalType, ResourceType, ResourceRoleMapping } from "@coa/ts-shared";
```

## Cross-Language Sync

Types in this package **must** stay in sync with their Python counterparts in `libs/common/src/coa_common/authnz_types.py`. When updating enums or interfaces here, update the Python models accordingly (and vice versa).
