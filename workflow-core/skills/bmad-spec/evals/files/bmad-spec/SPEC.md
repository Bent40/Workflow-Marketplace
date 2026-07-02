---
id: SPEC-link-shortener
companions: []
sources: []
---

> **Canonical contract.** This SPEC and the files in `companions:` are the complete, preservation-validated contract for what to build, test, and validate.

# Link Shortener

## Why
Marketing needs short, branded links for campaigns; the current third-party shortener
rate-limits us and owns our click data. A pain to solve: we lose attribution data and
get throttled mid-campaign.

## Capabilities

- id: CAP-1
  intent: A user can submit a long URL and receive a short branded link.
  success: Submitting a valid URL returns a short link on the branded domain that
    redirects to the original URL.

- id: CAP-2
  intent: A user can view the click count for a short link they created.
  success: The click count shown for a link equals the number of redirect hits recorded
    for it.

## Constraints
- Short codes are collision-free and never reused, even after a link is deleted.

## Non-goals
- No user accounts or auth in v1 (links are unlisted, knowledge-of-URL is access).

## Success signal
- A campaign runs entirely on branded short links with click data we own, with no
  third-party throttling during the campaign window.
