# ForestGuard local demo (Windows 11 / PowerShell)

This walkthrough uses the real FastAPI service and Python simulator. It labels
all generated telemetry as simulated. It does not send Telegram messages or
execute device commands. Use an isolated demo database so your normal database
is left unchanged.

## 1. Check prerequisites

Open PowerShell in the repository root:

```powershell
Set-Location 'C:\Users\hp\Downloads\FOREST GUARD'
python --version
node --version
npm.cmd --version
```

Use Python 3.10 or newer and Node.js 20.19+ or 22.12+. `npm.cmd` works in
PowerShell environments where the `npm.ps1` script is blocked by execution
policy. If `.venv\Scripts\python.exe` is missing, create the project's virtual
environment once:

```powershell
py -3.10 -m venv .venv
```

Install Python dependencies only when the virtual environment is new or imports
are missing:

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

Install frontend dependencies once, or again after the lock file changes:

```powershell
Set-Location frontend
npm.cmd ci
Set-Location ..
```

## 2. Prepare local settings without overwriting `.env`

Create `.env` from the example only if it does not exist. This command preserves
an existing `.env`:

```powershell
if (-not (Test-Path -LiteralPath .env)) {
    Copy-Item .env.example .env
    Write-Host 'Created .env from the example. Configure the local demo values below.'
} else {
    Write-Host 'Keeping the existing .env. Review its demo settings without replacing the file.'
}
notepad .env
```

In the local file, set or confirm these values. Keep any other existing private
settings intact. Choose a private, random value for the operator token and keep
it local; do not paste it into source code or a chat. The example file contains
blank placeholders only.

```dotenv
FORESTGUARD_DATABASE_PATH=data/forestguard-demo.sqlite3
FORESTGUARD_CORS_ORIGINS=["http://localhost:5173"]
FORESTGUARD_TELEGRAM_ENABLED=false
FORESTGUARD_DEVICE_COMMANDS_ENABLED=false
FORESTGUARD_DEVICE_COMMANDS_AUTH_TOKEN=<your-private-local-token>
```

Replace the angle-bracket value in your local `.env` with the token you chose;
do not leave the placeholder as the token. The separate `forestguard-demo`
database prevents the demo from adding rows to `data/forestguard.sqlite3`. Both
database files are ignored by Git. The browser asks for the token only when you
acknowledge an alert; it is sent for that request and is not saved to browser
storage. Do not enable Telegram for this walkthrough.

## 3. Start the backend and check health

Use three PowerShell terminals, all starting in the repository root. In
Terminal 1, activate the existing environment and run the backend in the
foreground:

```powershell
Set-Location 'C:\Users\hp\Downloads\FOREST GUARD'
.\.venv\Scripts\Activate.ps1
python -m uvicorn forestguard.main:app --app-dir backend --reload
```

Keep this terminal open. In Terminal 2, check the service:

```powershell
Set-Location 'C:\Users\hp\Downloads\FOREST GUARD'
Invoke-RestMethod http://127.0.0.1:8000/health
```

Continue when the response reports `status: ok` and `database: ok`. The API
loads `.env` at process startup, so restart the backend after changing it.

## 4. Start the dashboard

In Terminal 2, leave the backend health check and start Vite from the frontend
directory:

```powershell
Set-Location 'C:\Users\hp\Downloads\FOREST GUARD\frontend'
npm.cmd run dev
```

Open <http://127.0.0.1:5173> in a browser. The Vite development server proxies
`/api` and `/health` to the local backend. The dashboard polls every 15 seconds;
it does not use a server-sent-events stream. Keep the backend and Vite terminals
open while demoing.

## 5. Send simulated readings

Open Terminal 3 at the repository root. First send a short normal scenario:

```powershell
Set-Location 'C:\Users\hp\Downloads\FOREST GUARD'
.\.venv\Scripts\python.exe -m simulator --api-url http://127.0.0.1:8000 --scenario normal --duration 8 --interval 2 --seed 7 --station-prefix FG-DEMO-NORMAL
```

Then send a short smoke event. It should create an estimated risk incident from
the scenario's multiple elevated signals:

```powershell
.\.venv\Scripts\python.exe -m simulator --api-url http://127.0.0.1:8000 --scenario smoke_event --duration 12 --interval 2 --seed 7 --station-prefix FG-DEMO-SMOKE
```

Both commands return to the prompt when their duration ends. For a slower,
gradually changing example, `developing_risk` needs about one minute at the
default five-second interval to reach its later samples:

```powershell
.\.venv\Scripts\python.exe -m simulator --api-url http://127.0.0.1:8000 --scenario developing_risk --duration 65 --interval 5 --seed 7 --station-prefix FG-DEMO-DEVELOPING
```

In the dashboard, visit **Overview**, **Live monitoring**, **Analytics**,
**Devices**, **Alert center**, and **Settings**. Allow up to 15 seconds for the
next refresh. Look for `SIMULATED` labels and the smoke station's estimated
incident. The simulator uses illustrative coordinates; they are not deployment
locations. Risk states are estimates, not confirmed fires.

You can also verify the actual API responses from Terminal 3:

```powershell
Invoke-RestMethod 'http://127.0.0.1:8000/api/nodes?limit=200&offset=0'
Invoke-RestMethod 'http://127.0.0.1:8000/api/readings?is_simulated=true&limit=10&offset=0'
Invoke-RestMethod 'http://127.0.0.1:8000/api/alerts?is_simulated=true&status=ACTIVE&limit=100&offset=0'
```

## 6. Acknowledge and verify an incident

In **Alert center**, select a simulated active alert and open its details. The
acknowledgement button stays disabled until the operator token field is filled.
Enter the same local token configured in `.env` and submit. The alert should
close from the detail dialog and appear as **ACKNOWLEDGED** after dashboard
refresh. The API can verify that state:

```powershell
Invoke-RestMethod 'http://127.0.0.1:8000/api/alerts?is_simulated=true&status=ACKNOWLEDGED&limit=100&offset=0'
```

If a wrong token is entered, the page reports that it was not accepted, clears
the password field, and leaves the incident ACTIVE. A missing server token
causes the API to return an authorization-not-configured response. Never enable
real device commands for this demo; command records are unrelated to alert
acknowledgement and are not executed by hardware.

## 7. Stop cleanly

Each simulator run ends automatically at its configured duration. If you run
one without `--duration`, stop it with Ctrl+C. Stop Vite and the backend in
their respective terminals with Ctrl+C. These are foreground processes; no
background service or hidden window is started. The isolated demo database
remains available for the next run. Do not remove or replace your normal
database to reset demo data.

## Manual browser QA checklist

No browser automation dependency is included in this project. Automated
Vitest/jsdom tests do not count as browser testing. For a manual pass, open the
local dashboard and check:

- Navigate through all six areas and confirm the page remains responsive.
- Check the initial loading state, an empty database, and backend-unavailable
  state by stopping/restarting the backend.
- Confirm simulated telemetry and alerts have visible provenance labels and
  unavailable sensors never appear as zero.
- Open alert details; try a wrong token and verify the alert remains ACTIVE,
  the error is clear, and the password field clears. Then use the configured
  token and confirm ACKNOWLEDGED state after refresh.
- Resize to a narrow mobile viewport; check navigation, station cards, tables,
  charts, and the map. Map tiles require network access and may be unavailable.
- Enable the operating system's reduced-motion preference and confirm motion
  is reduced.

No manual browser test is implied by this checklist. This is a local prototype,
not a field-validated detection or emergency-response system.
