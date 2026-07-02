# Change trigger (discovered mid-sprint)

While building Story 2-1 (GPS tagging), the team discovered that the target
tablets used in the field have NO GPS hardware — they are Wi-Fi-only tablets with
no cellular/GNSS chip. Legal/procurement has confirmed the hardware cannot be
changed for this rollout.

This was discovered on day 6 of a 10-day sprint, with Story 2-1 about 60%
implemented against the assumption that on-device GPS is available.

Implication surfaced by the team: FR-3 ("each observation is tagged with the
surveyor's GPS location captured at creation time") cannot be satisfied as
written on this hardware. A surveyor could instead pick the site location
manually on a map, or the location could be inferred from a known site
assignment — but both are product decisions, not yet approved.
