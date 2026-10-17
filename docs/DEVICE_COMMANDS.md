# Device command API safety notes

Phase 7 stores authenticated operator requests for `REQUEST_STATUS` and
`SENSOR_SELF_TEST`. It provides command records and audit events; there is no
device transport, firmware receiver, or command executor in this application.
An accepted or completed record therefore does not prove that a device acted.

## Authorization and defaults

Command listing, creation, and acknowledgement require an `Authorization:
Bearer <token>` header. Configure `FORESTGUARD_DEVICE_COMMANDS_AUTH_TOKEN` on the
server and keep it out of source control, URLs, browser code, and logs. The
operator name is server-configured; request bodies cannot choose an identity.
If authorization is not configured, command routes return unavailable.

The same configured Bearer token is required by
`POST /api/alerts/{alert_id}/acknowledge`. Alert reads and the dashboard's
read-only views do not require it. For acknowledgement, the dashboard accepts
the operator token in a password field and sends it only in that request; it
does not embed or persist the token. Anyone with this shared token has the same
operator capability. It does not identify an individual or provide roles,
per-user revocation, or a production-grade identity system. Deployments needing
those properties should place the service behind an appropriate identity-aware
gateway or add individual authentication before wider exposure.

Real-command records are rejected unless
`FORESTGUARD_DEVICE_COMMANDS_ENABLED=true`. Simulated commands carry explicit
`is_simulated=true` provenance and remain distinguishable in records and
filters. The current command types do not include pump or relay actions.

Expiry is bounded by the configured maximum (one hour by default), and request
rates are limited per configured operator. Pending duplicates for the same
station, type, and provenance are rejected. Commands transition from `PENDING`
to `ACKNOWLEDGED`, then optionally to `COMPLETED` or `FAILED`; expired pending
commands become `EXPIRED`. Rejected attempts and accepted transitions are
audited. Completion is an externally reported status, not proof of execution.

## Physical safety boundary

Risk scores and alerts never create device commands. This phase does not actuate
pumps or any other equipment. Any future physical control requires a separate
review, hardware interlocks, independent safety validation, and a trustworthy
device acknowledgement path. No hardware behavior has been tested.
