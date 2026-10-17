# Detection logic and alert lifecycle

ForestGuard reports an **estimated environmental risk**. A risk state does not confirm a fire, dispatch responders, or validate sensor hardware. `demo-v1` is a reproducible software demonstration profile; it is not calibrated for a forest, sensor model, or jurisdiction.

## Demonstration profile

The only threshold and score profile is `DEMO_RISK_PROFILE` in `backend/forestguard/risk_profile.py`. An assessment stores its profile version so later profile changes do not make historical results ambiguous.

| Evidence | Demonstration threshold | Score contribution |
| --- | ---: | ---: |
| Elevated temperature | ≥ 38 °C | 22 |
| Extreme temperature | ≥ 50 °C | 35 instead of the elevated-temperature points |
| Low relative humidity | ≤ 25% | 20 |
| Elevated smoke sensor value | ≥ 300 sensor units | 35 |
| Elevated gas sensor value | ≥ 350 sensor units | 20 |
| Rapid temperature rise | ≥ 8 °C in the recent window | Included in the rapid-change signal |
| Rapid humidity drop | ≥ 15 percentage points in the recent window | Included in the rapid-change signal |
| Rapid smoke change | ≥ 100 units or ≥ 50% of the previous value | Included in the rapid-change signal |
| Rapid change signal | One or more rapid changes in the last hour | 20 |
| Sustained abnormal readings | At least 3 consecutive readings over at least 60 seconds, within 30 minutes | 30 |

The API accepts smoke and gas values from 0 to 100000 to accommodate generic sensor payloads. The 300 and 350 thresholds are arbitrary demonstration units. Smoke and gas readings vary by sensor, circuit, placement, and calibration, so these numbers must not be used to operate real equipment.

## Score and states

Evidence points are summed and capped at 100. Missing or invalid primary readings (temperature, humidity, or smoke) do not subtract points. They set a minimum score of 20 and a `WATCH` state, with explicit incomplete-data signals and reasons. In particular, missing smoke data is not treated as evidence that smoke is absent. Gas is optional and its absence is reported without lowering the score.

| State | Score and gate |
| --- | --- |
| `NORMAL` | 0–19, with all primary channels available |
| `WATCH` | 20–44, or incomplete primary sensor data |
| `WARNING` | 45–69; a score above 69 also remains `WARNING` when the critical evidence gate is not met |
| `CRITICAL` | Score ≥ 70 with at least 2 independent physical sensor domains, or score ≥ 60 with the sustained-reading gate met |

One uncorroborated sample cannot become `CRITICAL`, regardless of its value. The result includes the score, profile version, every signal considered, availability and trigger status, explanation strings, assessment timestamp, provenance, and device connectivity state. Contradictory cool/humid readings alongside elevated smoke are called out for sensor verification; they do not erase the smoke evidence.

Connectivity is independent of risk. Based on the server receipt time, a device is `ONLINE` through 300 seconds, `STALE` from 301 through 900 seconds, and `OFFLINE` after 900 seconds. A normal risk score does not imply an online device.

## History and provenance

Each reading is assessed against up to five preceding measurements from the same station, no later than that reading's device timestamp and with the same simulation provenance. A simulator sample cannot corroborate a hardware sample. Out-of-order readings still receive and retain their own assessment, but cannot replace a station's newest risk state or create, update, or resolve its current alert.

Primary sensor values may be omitted when unavailable. SQLite keeps the original Phase 3 non-null sensor columns and adds explicit availability columns; the API returns unavailable values as `null`. Existing rows migrate with their sensors marked available, preserving their previous meaning.

## Alert lifecycle

`WATCH`, `WARNING`, and `CRITICAL` create an alert. There is at most one open incident for a station and provenance (`is_simulated`), enforced by a partial unique index. Repeated evidence updates that incident instead of duplicating it. Changes in severity or explanation update its score, reasons, and timestamp. An acknowledged alert is reactivated when its severity escalates.

Acknowledgement is idempotent while an incident is open. Recovery requires **two consecutive newest `NORMAL` assessments** from that same provenance. The second normal assessment marks the alert `RESOLVED` and records the recovery reason. Resolved incidents remain in history; a later elevated reading can open a new incident.

These safeguards improve the demonstration's explanations and state handling. They do not replace field calibration, sensor diagnostics, human review, fire services, or physical safety systems.
