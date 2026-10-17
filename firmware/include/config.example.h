#pragma once

#include <math.h>

// Copy this file to config.h and edit it locally. config.h is ignored by Git.
// No credentials or wiring are assumed by this safe example.
#define FG_DEVICE_ID ""
#define FG_FIRMWARE_VERSION "0.1.0"
#define FG_WIFI_SSID ""
#define FG_WIFI_PASSWORD ""
#define FG_BACKEND_URL "" // Origin only, e.g. http://host-on-your-lan:8000
#define FG_BACKEND_ROOT_CA "" // PEM root CA for HTTPS; HTTPS is refused without it.

// Sampling, networking, and bounded in-RAM queue.
#define FG_SAMPLE_INTERVAL_MS 30000UL
#define FG_WIFI_RETRY_INTERVAL_MS 10000UL
#define FG_UPLOAD_INTERVAL_MS 5000UL
#define FG_HTTP_TIMEOUT_MS 5000UL
#define FG_HTTP_RETRIES 2
#define FG_OFFLINE_BUFFER_CAPACITY 8

// DHT22/AM2302 temperature + humidity adapter (Adafruit DHT library).
// Enable only after checking your exact board pinout and sensor datasheet.
#define FG_ENABLE_DHT22 0
#define FG_DHT_PIN -1

// Optional analog sensor channels. Set the channel enabled only after choosing
// a compatible module, a safe ADC pin, and a model-specific calibrated mapping.
// The affine mapping below is only a generic adapter; some sensors need a
// nonlinear model-specific conversion instead. NAN safely leaves it unavailable.
#define FG_ENABLE_SMOKE_ADC 0
#define FG_SMOKE_ADC_PIN -1
#define FG_SMOKE_UNITS_PER_COUNT NAN
#define FG_SMOKE_ZERO_OFFSET NAN

#define FG_ENABLE_GAS_ADC 0
#define FG_GAS_ADC_PIN -1
#define FG_GAS_UNITS_PER_COUNT NAN
#define FG_GAS_ZERO_OFFSET NAN

// Optional voltage-divider measurement. Do not enable without an actual,
// board-safe divider and measured calibration values for that circuit/battery.
#define FG_ENABLE_BATTERY_ADC 0
#define FG_BATTERY_ADC_PIN -1
#define FG_BATTERY_VOLTS_PER_COUNT NAN
#define FG_BATTERY_ZERO_OFFSET_VOLTS NAN
#define FG_BATTERY_EMPTY_VOLTS NAN
#define FG_BATTERY_FULL_VOLTS NAN

// Coordinates are omitted unless a real configured location is available.
#define FG_HAS_COORDINATES 0
#define FG_LATITUDE NAN
#define FG_LONGITUDE NAN

#if FG_SAMPLE_INTERVAL_MS < 1000UL || FG_SAMPLE_INTERVAL_MS > 86400000UL
#error "FG_SAMPLE_INTERVAL_MS must be between 1000 ms and 24 hours"
#endif
#if FG_WIFI_RETRY_INTERVAL_MS < 1000UL || FG_WIFI_RETRY_INTERVAL_MS > 300000UL
#error "FG_WIFI_RETRY_INTERVAL_MS must be between 1000 and 300000 ms"
#endif
#if FG_UPLOAD_INTERVAL_MS < 1000UL || FG_UPLOAD_INTERVAL_MS > 60000UL
#error "FG_UPLOAD_INTERVAL_MS must be between 1000 and 60000 ms"
#endif
#if FG_HTTP_TIMEOUT_MS < 100UL || FG_HTTP_TIMEOUT_MS > 30000UL
#error "FG_HTTP_TIMEOUT_MS must be between 100 and 30000 ms"
#endif
#if FG_ENABLE_DHT22 && FG_DHT_PIN < 0
#error "Set FG_DHT_PIN from the actual board wiring before enabling DHT22"
#endif
#if FG_ENABLE_DHT22 && FG_SAMPLE_INTERVAL_MS < 2000UL
#error "DHT22 sample interval must be at least 2000 ms"
#endif
#if FG_ENABLE_SMOKE_ADC && FG_SMOKE_ADC_PIN < 0
#error "Set a board-safe FG_SMOKE_ADC_PIN before enabling smoke ADC"
#endif
#if FG_ENABLE_GAS_ADC && FG_GAS_ADC_PIN < 0
#error "Set a board-safe FG_GAS_ADC_PIN before enabling gas ADC"
#endif
#if FG_ENABLE_BATTERY_ADC && FG_BATTERY_ADC_PIN < 0
#error "Set a board-safe FG_BATTERY_ADC_PIN before enabling battery ADC"
#endif
#if FG_OFFLINE_BUFFER_CAPACITY < 1 || FG_OFFLINE_BUFFER_CAPACITY > 64
#error "FG_OFFLINE_BUFFER_CAPACITY must be between 1 and 64"
#endif
#if FG_HTTP_RETRIES < 0 || FG_HTTP_RETRIES > 4
#error "FG_HTTP_RETRIES must be between 0 and 4"
#endif
