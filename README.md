# ForestGuard

ForestGuard is a forest monitoring prototype for collecting environmental sensor readings, assessing potential fire risk, and presenting alerts. Simulation data will always be identified as simulated; this project does not confirm fires or replace field-tested safety systems.

## Project status

- [x] Phase 1: repository setup and implementation plan
- [x] Phase 2: backend foundation, settings, SQLite initialization, and health checks
- [x] Phase 3: station and reading APIs
- [x] Phase 4: explainable risk assessment and alert lifecycle
- [x] Phase 5: deterministic sensor simulator
- [x] Phase 6: optional Telegram notifications
- [x] Phase 7: safe device-command policy (no hardware execution)
- [x] Phase 8: React/TypeScript mission-control dashboard
- [x] Phase 9: configurable ESP32 telemetry firmware reference
- [x] Phase 10: integration, documentation, and CI

## Backend quick start

Python 3.10 or newer is required.

```powershell
py -3.10 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
if (-not (Test-Path -LiteralPath .env)) { Copy-Item .env.example .env }
uvicorn forestguard.main:app --app-dir backend --reload
```

The service exposes `GET /` and `GET /health`. Phase 3 adds monitoring station and reading APIs under `/api/nodes` and `/api/readings`. Phase 4 adds persisted risk assessments and alert routes under `/api/alerts`, including acknowledgement and recovery. SQLite migrations run on application startup. The default database path is `data/forestguard.sqlite3`; set `FORESTGUARD_DATABASE_PATH` to choose another location.

Station and reading collection endpoints use `limit` and `offset` pagination (maximum `limit`: 200). Reading queries can filter by `node_id` and `is_simulated`. Ingestion requires an explicit boolean `is_simulated`, a timezone-aware timestamp when supplied, temperature from -80 to 100 °C, relative humidity from 0 to 100%, smoke and gas values from 0 to 100000, paired coordinates within latitude/longitude bounds, and an optional battery percentage from 0 to 100. Timestamps are stored in UTC. These broad sensor input limits validate payload shape; they are not calibrated fire-risk thresholds.

Run backend checks with `python -m pytest` and `ruff check backend`.

## Python sensor simulator

The simulator uses the existing reading API and marks every generated reading with `is_simulated: true`. With the backend running, use `python -m simulator --scenario normal --seed 7` from the repository root. See [simulator/README.md](simulator/README.md) for installation, all scenarios, PowerShell commands, API verification, and limitations. Simulator coordinates are illustrative demo locations; risk thresholds are demonstration values and are not field calibrated.

See [docs/DETECTION_LOGIC.md](docs/DETECTION_LOGIC.md) for the demonstration risk thresholds, evidence rules, connectivity states, and alert recovery policy.

## Optional Telegram notifications

Notifications are disabled by default. The backend queues only new eligible alerts and severity escalations; delivery runs in a separate background worker and never delays reading ingestion. A schema v4 outbox records pending, sent, failed, and skipped events. Delivery attempts have configured HTTP timeouts and a finite retry count. Failures are persisted and logged without bot credentials. Telegram delivery is best effort: an ambiguous network timeout can occur after Telegram accepted a message, so an external service cannot guarantee exactly-once delivery.

To configure locally, create a bot with [BotFather](https://t.me/BotFather), keep the token private, and send `/start` to the bot (or add it to the intended group and send a message). After temporarily setting the token in your local process environment, this PowerShell command reads the latest update and prints only its chat ID:

```powershell
$update = Invoke-RestMethod -Uri ("https://api.telegram.org/bot{0}/getUpdates" -f $env:FORESTGUARD_TELEGRAM_BOT_TOKEN)
$update.result[-1].message.chat.id
```

Do not share the request URL or its token. Copy `.env.example` to `.env` and set the token, chat ID, and enable flag there. `.env` is ignored by Git.

```powershell
if (-not (Test-Path -LiteralPath .env)) { Copy-Item .env.example .env }
# Edit .env locally and set:
# FORESTGUARD_TELEGRAM_ENABLED=true
# FORESTGUARD_TELEGRAM_BOT_TOKEN=<your private bot token>
# FORESTGUARD_TELEGRAM_CHAT_ID=<destination chat ID>
# FORESTGUARD_TELEGRAM_MIN_SEVERITY=WARNING
# FORESTGUARD_TELEGRAM_TIMEOUT_SECONDS=5
# FORESTGUARD_TELEGRAM_RETRIES=2
uvicorn forestguard.main:app --app-dir backend --reload
```

Choose `WATCH`, `WARNING`, or `CRITICAL` as the minimum severity. To disable delivery, set `FORESTGUARD_TELEGRAM_ENABLED=false` in `.env` and restart the backend. If enabled without both credentials, the backend stays operational, logs that notifications are unavailable, and records eligible events as skipped. For a safe simulated test, start the backend with notifications enabled and run `python -m simulator --scenario smoke_event --duration 15 --seed 7`; the message is visibly labeled `[SIMULATION — NOT A REAL FIRE]`. Do not paste bot tokens into chat, source code, tickets, or committed configuration.

For troubleshooting, confirm the bot can message the destination, verify the chat ID and minimum severity, and inspect backend logs for delivery outcomes. Use `GET /api/alerts?is_simulated=true` to verify simulated alerts. Outbox entries, bounded attempts, and sanitized failure reasons are stored in SQLite's `notification_log` table; the bot token and chat ID are never stored there.

## Authorized device-command records

Phase 7 adds authenticated, audited command records for `REQUEST_STATUS` and `SENSOR_SELF_TEST`. Real command creation is disabled by default, and no device executor or pump actuation path exists. See [docs/DEVICE_COMMANDS.md](docs/DEVICE_COMMANDS.md) for authorization setup, lifecycle, limits, and safety boundaries.

Alert acknowledgement is also an operator-only state change. It uses the same server-side `FORESTGUARD_DEVICE_COMMANDS_AUTH_TOKEN` Bearer credential; configure it on the backend before acknowledgement is available. The dashboard asks the operator for the token only when acknowledging an alert and sends it with that request only. It is not part of the frontend build or stored in browser storage. This is a shared-token gate, not individual identity, role-based access control, or a substitute for a production identity provider. Alert listing and the rest of the dashboard remain read-only and available without an operator token.

## Mission-control dashboard

The React/TypeScript dashboard is in [frontend](frontend/README.md). Start the FastAPI backend and the Vite development server in separate terminals. The dashboard reads stations, readings, alert records, and alert summaries from the live API; it does not seed demo telemetry. It refreshes every 15 seconds and labels simulated data explicitly. Map tiles require a browser internet connection.

For the complete Windows 11 / PowerShell local demo walkthrough, including a separate demo database, simulator scenarios, protected alert acknowledgement, and a manual browser checklist, see [docs/DEMO_GUIDE.md](docs/DEMO_GUIDE.md).

## ESP32 telemetry firmware

The PlatformIO/Arduino reference firmware is in [firmware](firmware/platformio.ini). It submits validated physical readings with `is_simulated: false`, omits unavailable sensor channels, and uses a bounded RAM queue while disconnected. Copy `firmware/include/config.example.h` to the ignored local `firmware/include/config.h` and configure only hardware that is actually present. DHT22 support is optional; smoke, gas, battery, pins, and calibration are unselected until verified for the actual hardware. See [docs/HARDWARE_SETUP.md](docs/HARDWARE_SETUP.md) for wiring constraints, setup, build/upload commands, and known limitations. No physical hardware test has been performed.

## Project components

The backend lives in `backend/forestguard`, automated checks in `backend/tests`, the Python simulator in `simulator/`, the dashboard in `frontend/`, and the ESP32 firmware reference in `firmware/`.

## Reproducible checks

From the repository root, run the backend, simulator, and host-side firmware contract tests plus Ruff:

```powershell
python -m pytest
ruff check backend simulator firmware/tests
git diff --check
```

Run the frontend test, lint, TypeScript check, and production build from `frontend/`:

```powershell
npm ci
npm test
npm run lint
npx tsc -b
npm run build
```

The build script also runs TypeScript project checks. If PlatformIO Core is installed, build the ESP32 reference with `python -m platformio run --project-dir firmware`; this compiles the firmware but does not validate hardware. Physical sensor, Wi-Fi, calibration, and fire-detection validation require the actual selected board and components.

## Prototype limitations

Risk thresholds will be demonstration settings until calibrated and validated against field data. Reading provenance is a client-supplied `is_simulated` flag; it labels records but does not authenticate a device or prove that a non-simulated payload came from physical hardware. Reading ingestion, station registration, and station updates currently have no authentication, and the API has no global request-body size limit. Keep the service on a trusted development network or behind an appropriately secured gateway; do not expose it directly to the public internet. No physical sensor, hardware deployment, fire detection, or notification delivery has been verified. Notifications are disabled by default, and automatic pump activation is outside the system's behavior.
