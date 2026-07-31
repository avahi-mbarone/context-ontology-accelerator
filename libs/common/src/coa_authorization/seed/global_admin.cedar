// Global Admin: full access to all actions on all resources
permit (
  principal,
  action,
  resource
)
when { principal.globalRoles.contains("platform-admin") };
