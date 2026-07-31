// Default policy — applied to every authenticated principal on every
// authorization decision (the authorizer always loads ROLE#default in
// addition to the principal's resolved roles). It therefore also carries the
// archived-namespace mutation guard below, which must participate in every
// evaluation regardless of the principal's roles.

// All authenticated users can list namespaces (filtering in API logic).
permit (
  principal,
  action == SCL::Action::"list",
  resource is SCL::Namespace
);

// Non-ACTIVE-namespace mutation guard.
//
// A namespace that is not ACTIVE — ARCHIVED (frozen, data retained for
// audit), DELETING (async deletion pipeline running), or DELETE_FAILED
// (deletion attempt failed, awaiting retry) — must never accept a MUTATING
// action against it or its child resources (sources, metrics, ontologies,
// grants, roles). Because this is a `forbid`, it overrides every `permit` —
// including platform-admin and namespace-owner — so "no mutations unless
// ACTIVE" is a hard invariant, not a role-overridable default. Blocking
// DELETING/DELETE_FAILED (not just ARCHIVED) prevents a create/update racing
// against the deletion pipeline's cleanup steps, or against a retry of a
// failed deletion, which could otherwise resurrect a child resource the
// pipeline just tore down (or is about to).
//
// It lives in default.cedar (rather than a standalone seed file) so it is
// always loaded: the authorizer always includes ROLE#default in the evaluated
// policy set, so the guard is guaranteed to participate without any extra
// seeding or per-request policy loading.
//
// Intentionally NOT blocked in any non-ACTIVE status:
//   - Reads: viewNamespace, list, query, readMetric, searchDocuments
//   - setNamespaceStatus → reactivate (ARCHIVED -> ACTIVE)
//   - deleteNamespace     → tear down / retry (ARCHIVED or DELETE_FAILED -> DELETING)
//
// The authorizer only sets context.namespaceStatus for mutating routes that
// carry a namespaceId, so the `context has namespaceStatus` guard leaves
// platform-scoped and create routes (no namespace yet) unaffected.
forbid (
  principal,
  action in [
    SCL::Action::"manageSource",
    SCL::Action::"manageMetric",
    SCL::Action::"manageOntology",
    SCL::Action::"manageNamespace",
    SCL::Action::"grantPermissions",
    SCL::Action::"manageRoles"
  ],
  resource
)
when {
  context has namespaceStatus && context.namespaceStatus != "ACTIVE"
};
