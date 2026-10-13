# Platform Architecture

## 4. Service communication

4.1 Internal services communicate over REST/JSON.

4.2 The public edge API is REST/JSON for third-party clients.

4.3 Inter-service authentication uses mTLS bound to the REST channel.

## 12. Traceability

| Req  | Mechanism                      | Test |
|------|--------------------------------|------|
| FR-3 | inter-service transport (REST) | T-12 |
