// Namespace Maintainer: full access within their namespace (same as owner)
permit (
  principal,
  action,
  resource
)
when {
  principal.resourceRoles.contains({
    "role": "namespace-maintainer",
    "resourceUID": resource.id
  })
};
