# ForestGuard mission control

The dashboard reads live station, reading, alert, and alert-summary data from
the ForestGuard API. It does not seed example stations or risk values. Simulated
readings and alerts stay explicitly labeled, and missing assessments display as
unassessed.

## Run locally

Use Node.js 20.19+ or 22.12+ and npm.

Start the backend from the repository root in one terminal:

```powershell
.\.venv\Scripts\Activate.ps1
uvicorn forestguard.main:app --app-dir backend --reload
```

In another terminal:

```powershell
cd frontend
npm ci
npm run dev
```

Vite serves the dashboard at `http://localhost:5173` and proxies `/api` and
`/health` to `http://127.0.0.1:8000`. Set `VITE_API_BASE_URL` only when the API
is hosted at a different origin. Cross-origin deployments must also configure
the backend's `FORESTGUARD_CORS_ORIGINS` accordingly.

The station map plots only coordinates returned by the backend and uses
OpenStreetMap tiles, which require a browser internet connection. The app
refreshes dashboard data every 15 seconds and can also be refreshed manually.

## Checks

```powershell
npm test
npm run lint
npm run build
```
