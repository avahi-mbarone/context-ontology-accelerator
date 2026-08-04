<!--
Ported from the internal merge-request template. Two deliberate differences:
the CI section reflects what actually runs on a pull request here (lint, unit
tests and cdk synth via GitHub Actions), and integration tests are described as
requiring a deployed environment rather than being expected of a contributor.
-->

## Change Description

### What this change does:

<!-- Describe what this change accomplishes -->

### Why it is needed:

<!-- The problem being solved, or the behaviour being corrected -->

### Related issues

<!-- Link issues this closes, e.g. "Closes #123" -->

## Observation step

<!--
A concrete, falsifiable check a reviewer can run: the command or action, and the
expected output. "Tests pass" is not an observation step.

Example: `uv run pytest packages/sources/tests/unit -q` — expect 880 passed.
-->

## Testing Performed

### Unit tests

<!-- What you added or changed, and the command to run them -->

### Integration tests

<!--
Integration tests need a deployed environment and AWS credentials, so they run in
the maintainers' pipeline rather than on a pull request. Note here whether this
change needs integration coverage, and describe any manual verification you did.
-->

### Frontend changes

<!--
For changes under packages/web-app, attach screenshots of the affected states
(empty, loading, error, populated). A passing hook test does not show that a page
renders correctly.
-->

## Checklist

- [ ] Tests added or updated for the changed behaviour
- [ ] `make lint` passes locally
- [ ] Documentation updated if behaviour, configuration or commands changed
- [ ] No secrets, credentials, account identifiers or internal hostnames added
- [ ] Commits are scoped and the diff contains no unrelated changes
