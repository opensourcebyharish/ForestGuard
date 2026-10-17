# ESP32 hardware setup (Phase 9 reference)

This is an integration template, not a validated hardware design. No ESP32 board,
sensor, ADC channel, battery circuit, or pin assignment was supplied with the
project. Every sensor adapter is disabled in the committed example configuration.
Do not energize a circuit until its board and sensor datasheets have been checked.

The firmware targets PlatformIO's generic `esp32dev` Arduino board definition.
The supported digital example is an optional DHT22/AM2302 temperature and
relative-humidity sensor using Adafruit's DHT sensor library 1.4.7 and Adafruit
Unified Sensor 1.1.15. Smoke and gas are configurable generic analog interfaces;
they do not name or claim compatibility with a particular sensor. Battery
measurement is disabled unless a measured divider circuit and calibration are
provided. The firmware contains no actuators or device-command execution.

## Components and configurable connections

| Interface | Connection | Firmware setting | Limitations |
| --- | --- | --- | --- |
| ESP32 development board | USB for power/programming; board-specific serial adapter | PlatformIO `esp32dev` target | Confirm the exact ESP32 variant, logic levels, and available pins first. |
| Optional DHT22/AM2302 | Sensor VCC to the sensor's specified supply; GND to common GND; DATA to a locally selected digital GPIO. A bare sensor may need the pull-up specified by its datasheet; many modules include one. | `FG_ENABLE_DHT22=1`, `FG_DHT_PIN=<verified GPIO>` | Verify exact module pin order and supply requirements. The sample period must be at least 2 seconds. |
| Optional smoke sensor | Only a module with a documented, ESP32-safe analog output and a model-specific conversion/calibration. Connect its conditioned output to a verified ADC input and share ground. | `FG_ENABLE_SMOKE_ADC=1`, `FG_SMOKE_ADC_PIN`, calibrated scale/offset or a replacement sensor adapter | No smoke sensor model or calibration is selected. Do not transmit raw ADC counts as calibrated smoke units. Nonlinear sensors need a model-specific conversion, not the example affine mapping. |
| Optional gas sensor | As specified for the chosen sensor, with verified signal conditioning and model-specific conversion. | `FG_ENABLE_GAS_ADC=1`, `FG_GAS_ADC_PIN`, calibration or a replacement adapter | No gas sensor model or calibration is selected. Some modules need warm-up and nonlinear compensation. |
| Optional battery voltage | Battery through a designed, board-safe measurement circuit (often a divider) to a verified ADC input; common reference as required by the circuit. | `FG_ENABLE_BATTERY_ADC=1`, `FG_BATTERY_ADC_PIN`, measured volts/count and offset, measured empty/full voltage | No battery percentage is inferred from ESP32 power or guessed. Design and verify input protection, resistor values, and calibration for the actual battery and board. |

There are deliberately **no default GPIO numbers**. Select pins from the exact
board pinout; avoid boot-strapping, flash, input-only, or otherwise reserved pins
as appropriate for that board. ESP32 GPIOs are not 5 V tolerant. Never connect a
sensor output above the selected board's permitted input range. A voltage divider
or signal-conditioning circuit must be designed for the specific output, not
assumed from the word “analog.”

The backend accepts temperature `-80..100 °C`, humidity `0..100%`, smoke and gas
`0..100000` sensor units, and battery `0..100%`. These are payload bounds, not
sensor specifications or field-calibrated risk thresholds. Missing channels are
omitted. At least one valid temperature, humidity, smoke, or gas value is needed
to send a reading. Battery alone does not satisfy that requirement. Coordinates
are omitted unless both real values are intentionally configured and pass their
latitude/longitude bounds.

## Local configuration and secrets

From the repository root, create a local configuration file:

```powershell
Copy-Item firmware/include/config.example.h firmware/include/config.h
```

Edit `firmware/include/config.h` locally. It is ignored by Git. Set a valid device
ID (1–64 characters, beginning with a letter or digit and containing only
letters, digits, `.`, `_`, or `-`), Wi-Fi SSID/password, and a backend origin
reachable from the ESP32. Do not log or share the local header. The firmware
never prints credentials and has no Telegram token, command-authorization token,
or command endpoint.

The example samples every 30 seconds, retries Wi-Fi every 10 seconds, limits each
HTTP attempt to 5 seconds with two retries, spaces uploads by at least 5 seconds,
and buffers eight samples in RAM. Adjust these values for the actual sensor and
deployment constraints; the configuration header enforces broad bounds.

Configure only the sensor interfaces that physically exist. For an analog
channel, leaving its scale/offset at `NAN` keeps it unavailable. The affine
mapping is only a placeholder for sensors that are genuinely calibrated by such
a mapping. Replace it with a sensor-specific adapter for sensors requiring a
curve, warm-up compensation, or other model. Do not use the demonstration risk
profile as a calibration reference.

Set coordinates only if they are real station coordinates. Set battery fields
only if the actual voltage-measurement circuit has been designed and measured.
Both fields are optional and are not inferred by software.

Prefer HTTPS with the correct root CA in the local configuration. HTTPS is
refused when no CA is configured; certificate checking is never disabled. Plain
HTTP is useful only for an isolated trusted LAN during development and does not
protect telemetry in transit. The backend currently accepts reading ingestion
without a device credential; do not expose that endpoint directly to an
untrusted network.

## Backend and firmware build

Start the backend on a host reachable from the ESP32. `127.0.0.1` refers to the
ESP32 itself from the device's perspective; use the host's reachable LAN address
or a properly secured HTTPS endpoint in the local firmware configuration.

Install PlatformIO Core in a development environment and build from the
repository root:

```powershell
python -m pip install platformio
python -m platformio run --project-dir firmware
```

After selecting the actual serial port and board connection, upload and inspect
serial diagnostics:

```powershell
python -m platformio run --project-dir firmware --target upload --upload-port COM3
python -m platformio device monitor --port COM3 --baud 115200
```

Replace `COM3` with the port reported by the local operating system. Uploading
flashes the attached board; no hardware was available during this implementation
to verify the port, wiring, sensor readings, or operation.

## Diagnostics and recovery

Serial output runs at 115200 baud. It reports firmware/device ID, Wi-Fi connect
and reconnect state, time-sync availability, unavailable sensor channels, RAM
queue occupancy, retryable HTTP failures, API rejection, and accepted API
readings. It never prints Wi-Fi credentials, request bodies, response bodies,
tokens, or authorization headers.

Samples are attempted every configured interval. The queue stores at most eight
samples in RAM by default. It does not survive reset or power loss; when full it
drops the oldest buffered reading to retain recent measurements. Retries and
HTTP timeouts are bounded. HTTP 201 is accepted only when the response JSON
contains a positive reading ID, the configured station ID, and
`is_simulated: false`. Rejected client responses are discarded rather than
retried forever.

The current reading API has no idempotency key. If the server commits a reading
but its response is lost, a retry can create a duplicate record; delivery is
best-effort across ambiguous network failures, not exactly-once.

An NTP UTC timestamp is included only after the clock has synchronized. Until
then the timestamp field is omitted, which the backend permits; the backend
records its own receive time. No fabricated timestamp is sent.

Troubleshooting:

- **No readings:** set a valid device ID and backend URL, enable at least one
  installed sensor, check its serial diagnostics, and confirm the backend is
  reachable from the device's network.
- **HTTP 422:** check the accepted ranges, the paired-coordinate rule, node ID,
  and that at least one valid sensor channel is present.
- **HTTP 404/other 4xx:** confirm the URL ends at the backend origin (the
  firmware appends `/api/readings`) and inspect server logs without sharing
  secrets.
- **HTTPS refused:** install the correct CA certificate in local configuration;
  do not disable certificate verification.
- **Repeated missing DHT values:** verify the exact module pinout, configured
  GPIO, common ground, pull-up requirements, supply, and sample period.
- **Analog channel omitted:** confirm the correct ADC pin and signal-conditioning
  circuit, then provide a measured, sensor-specific conversion. `NAN` scale or
  offset intentionally disables that channel.
- **No timestamp:** check network access to the configured NTP services. The
  server receive timestamp is used until UTC synchronization succeeds.
- **Queue losses:** restore network connectivity; a full RAM queue discards its
  oldest entry and a power cycle clears the whole queue.

## Calibration and safety boundary

No calibration, field accuracy, smoke-alarm performance, fire detection,
battery-state accuracy, or environmental suitability is claimed. Sensor
placement, weather exposure, enclosure, power, drift, cross-sensitivity, and
maintenance require independent engineering and field validation. Software
validation cannot guarantee physical safety. The firmware has no pump, relay,
GPIO actuator, or device-command handling and must not be used as a life-safety
system.
