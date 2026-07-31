// Namespace DataAnalyst: read/query access within their namespace.
// Role name "data-analyst" (kebab-case) matches the identifier stored in DynamoDB.
//
// Grants:
//   - query, readMetric, searchDocuments (scoped via resource.namespace)
//   - viewNamespace, list (scoped via resource.id)
//
// Does NOT grant any write/manage actions.
permit (
  principal,
  action == SCL::Action::"query",
  resource
)
when {
  principal.resourceRoles.contains({
    "role": "data-analyst",
    "resourceUID": resource.namespace
  })
};

permit (
  principal,
  action == SCL::Action::"readMetric",
  resource
)
when {
  principal.resourceRoles.contains({
    "role": "data-analyst",
    "resourceUID": resource.namespace
  })
};

permit (
  principal,
  action == SCL::Action::"searchDocuments",
  resource
)
when {
  principal.resourceRoles.contains({
    "role": "data-analyst",
    "resourceUID": resource.namespace
  })
};

permit (
  principal,
  action == SCL::Action::"translateQuery",
  resource
)
when {
  principal.resourceRoles.contains({
    "role": "data-analyst",
    "resourceUID": resource.namespace
  })
};

permit (
  principal,
  action == SCL::Action::"traverseGraph",
  resource
)
when {
  principal.resourceRoles.contains({
    "role": "data-analyst",
    "resourceUID": resource.namespace
  })
};

permit (
  principal,
  action == SCL::Action::"viewNamespace",
  resource
)
when {
  principal.resourceRoles.contains({
    "role": "data-analyst",
    "resourceUID": resource.id
  })
};

permit (
  principal,
  action == SCL::Action::"list",
  resource
)
when {
  principal.resourceRoles.contains({
    "role": "data-analyst",
    "resourceUID": resource.id
  })
};
