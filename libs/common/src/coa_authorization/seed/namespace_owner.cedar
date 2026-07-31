// Namespace Owner: full access within their namespace.
// Matches when the principal holds the "namespace-owner" resource role
// for the target resource's ID. Grants all actions (manage, delete, grant, etc.).
// Role name uses kebab-case to align with the role identifiers stored in DynamoDB.
permit (
  principal,
  action,
  resource
)
when {
  principal.resourceRoles.contains({
    "role": "namespace-owner",
    "resourceUID": resource.id
  })
};
