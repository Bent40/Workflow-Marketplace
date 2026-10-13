---
applyTo: "server/**,api/**,src/server/**,src/api/**"
---
<!-- GENERATED FILE — do not edit by hand. -->
<!-- Source of truth: core/rules/*.yaml + core/profiles/*.yaml + core/targets/*.yaml. Regenerate with scripts/generate-adapters.py. -->

# GitHub Copilot — review instructions: backend

What to look for when REVIEWING changes to files matching the **backend** path group. Profile: **civilian**. (Review focus — distinct from the authoring instructions in backend.instructions.md.)

## Validate user-facing inputs before trusting or persisting them.
<!-- rule:rookie.no_missing_input_validation severity:high review -->

- Confirm inputs crossing a trust boundary (request bodies, params, uploads, external payloads) are validated for type/range/length/shape before use or persistence; flag raw trust.

## List endpoints that can grow unbounded must paginate or limit results.
<!-- rule:rookie.no_unbounded_list_endpoint severity:high review -->

- Flag list/query endpoints with no pagination or explicit limit; confirm bounded result sets and the absence of N+1 cascades.
