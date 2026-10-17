# ForestGuard Python sensor simulator

This tool sends explicitly simulated readings to the existing ForestGuard API. It does not implement risk scoring; the backend evaluates and stores every accepted reading. The default coordinates are illustrative points near Yosemite National Park and do not represent deployed stations or a real sensor network.

## Requirements and startup

Use Python 3.10 or later. From the repository root in PowerShell, install the project's existing dependencies and start the backend in separate terminals:

```powershell
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
uvicorn forestguard.main:app --app-dir backend --reload
```

In another terminal at the repository root, run a scenario:

```powershell
python -m simulator --scenario normal --seed 7
```

The simulator uses only Python's standard library for HTTP; it adds no runtime dependency. It creates stations with recognizable `FG-SIM-###` IDs if missing, and all readings include `is_simulated: true`.

## Scenarios

```powershell
python -m simulator --scenario normal --stations 2 --interval 5 --duration 60 --seed 7
python -m simulator --scenario developing_risk --interval 5 --seed 7
python -m simulator --scenario smoke_event --duration 30 --seed 7
python -m simulator --scenario recovery --duration 60 --seed 7
python -m simulator --scenario sensor_failure --duration 60 --seed 7
```

`normal` varies gently around ordinary conditions. `developing_risk` gradually increases temperature and lowers humidity. `smoke_event` emits sustained smoke, gas, heat, and low-humidity evidence that exercises the existing backend corroboration rules. `recovery` gradually returns from elevated conditions toward baseline. `sensor_failure` explicitly sends unavailable smoke and gas channels on a repeating schedule; other available sensors remain present. All generated values stay within the API's broad input limits. A seed makes the generated sequence repeatable.

For a custom local API or station prefix:

```powershell
python -m simulator --api-url http://127.0.0.1:8000 --stations 3 --station-prefix FG-SIM --scenario normal --interval 3 --duration 30 --seed 42
```

Omit `--duration` to run until Ctrl+C. The simulator prints a sent/failure summary when stopped. It uses request timeouts and bounded retries for connection failures, timeouts, rate limits, and server errors; invalid client requests are reported without retrying. An HTTP/API connection failure is counted and never described as a successful reading.

Typical console output looks like this (the summary values depend on runtime and API availability):

```text
SIMULATED DATA ONLY | scenario=normal | stations=1
sent simulated reading: FG-SIM-001
Stopping simulator...
Simulator stopped. Simulated readings sent: 1; failures: 0.
```

## Verification

Inspect recent simulated readings and alerts with:

```powershell
Invoke-RestMethod "http://127.0.0.1:8000/api/readings?is_simulated=true&limit=10"
Invoke-RestMethod "http://127.0.0.1:8000/api/alerts?is_simulated=true&limit=10"
Invoke-RestMethod "http://127.0.0.1:8000/api/alerts/summary"
```

Generated readings and risk states are demonstrations only. The documented thresholds are not field-calibrated, the coordinates are illustrative, and a risk state is not confirmation of a fire or a substitute for validated detection and emergency procedures.
