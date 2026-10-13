---
applyTo: "server/**,api/**,src/server/**,src/api/**"
---
<!-- GENERATED FILE — do not edit by hand. -->
<!-- Source of truth: core/rules/*.yaml + core/profiles/*.yaml + core/targets/*.yaml. Regenerate with scripts/generate-adapters.py. -->

# GitHub Copilot — path-scoped instructions: backend

Instructions applied only to files matching the **backend** path group. Server routes, controllers, request/response contracts, services. Profile: **civilian**.

## Validate user-facing inputs before trusting or persisting them.
<!-- rule:rookie.no_missing_input_validation severity:high -->

- Validate user-facing input; don't trust it raw.
  Validate and constrain inputs that cross a trust boundary (request bodies,
  query params, uploaded files, external payloads) before using or persisting
  them — type, range, length, and shape. Reject or sanitize what does not fit.

## List endpoints that can grow unbounded must paginate or limit results.
<!-- rule:rookie.no_unbounded_list_endpoint severity:high -->

- Paginate/limit list endpoints; don't return unbounded result sets.
  An endpoint or query that can return an unbounded number of rows must paginate
  or apply an explicit limit. Returning everything invites slow responses,
  memory blowups, and N+1 cascades as data grows.
