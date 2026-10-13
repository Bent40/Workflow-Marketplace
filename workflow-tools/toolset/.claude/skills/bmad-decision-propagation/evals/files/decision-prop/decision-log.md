# Decision Log

## D-API1 — Internal inter-service transport is gRPC (resolved, human-approved)

All **internal** service-to-service calls use **gRPC**. This **supersedes** the earlier
"REST/JSON between internal services" allowance. The **public edge API stays REST/JSON**
for third-party clients — explicitly **out of scope** of this decision.
