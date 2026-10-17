#include <Arduino.h>
#include <ArduinoJson.h>
#include <HTTPClient.h>
#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <time.h>

#include <cmath>
#include <cstdio>
#include <cstring>

#include "config.h"

#if FG_ENABLE_DHT22
#include <DHT.h>
DHT dht(FG_DHT_PIN, DHT22);
#endif

namespace {

constexpr time_t kReliableUtcAfter = 1704067200; // 2024-01-01T00:00:00Z
constexpr size_t kQueueCapacity = FG_OFFLINE_BUFFER_CAPACITY;

struct BufferedReading {
  bool hasTemperature = false;
  bool hasHumidity = false;
  bool hasSmoke = false;
  bool hasGas = false;
  bool hasBattery = false;
  bool hasCoordinates = false;
  float temperatureC = 0.0f;
  float humidityPercent = 0.0f;
  float smokeValue = 0.0f;
  float gasValue = 0.0f;
  float batteryPercent = 0.0f;
  float latitude = 0.0f;
  float longitude = 0.0f;
  char timestamp[25] = {};
};

BufferedReading offlineQueue[kQueueCapacity];
size_t queueHead = 0;
size_t queueSize = 0;
unsigned long lastSampleAt = 0;
unsigned long lastWifiAttemptAt = 0;
unsigned long lastUploadAt = 0;
bool timeSyncRequested = false;

bool validNodeId(const char *value) {
  size_t length = 0;
  while (length <= 64 && value[length] != '\0') ++length;
  if (length == 0 || length > 64) return false;
  const auto alphaNumeric = [](char c) {
    return (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') || (c >= '0' && c <= '9');
  };
  if (!alphaNumeric(value[0])) return false;
  for (size_t index = 1; index < length; ++index) {
    const char c = value[index];
    if (!alphaNumeric(c) && c != '.' && c != '_' && c != '-') return false;
  }
  return true;
}

bool inRange(float value, float minimum, float maximum) {
  return std::isfinite(value) && value >= minimum && value <= maximum;
}

bool makeUtcTimestamp(char *output, size_t outputSize) {
  const time_t now = time(nullptr);
  if (now < kReliableUtcAfter) return false;
  struct tm utc{};
  if (gmtime_r(&now, &utc) == nullptr) return false;
  return strftime(output, outputSize, "%Y-%m-%dT%H:%M:%SZ", &utc) > 0;
}

void addToOfflineQueue(const BufferedReading &reading) {
  if (queueSize == kQueueCapacity) {
    queueHead = (queueHead + 1) % kQueueCapacity;
    --queueSize;
    Serial.println("Offline queue full; discarded its oldest sample to retain recent telemetry.");
  }
  const size_t tail = (queueHead + queueSize) % kQueueCapacity;
  offlineQueue[tail] = reading;
  ++queueSize;
  Serial.printf("Sample buffered in RAM (%u/%u).\n", static_cast<unsigned>(queueSize),
                static_cast<unsigned>(kQueueCapacity));
}

bool readCalibratedAdc(int pin, float scale, float offset, float minimum, float maximum,
                       float &output) {
  if (pin < 0 || !std::isfinite(scale) || !std::isfinite(offset)) return false;
  uint32_t total = 0;
  constexpr int sampleCount = 8;
  for (int sample = 0; sample < sampleCount; ++sample) {
    total += static_cast<uint32_t>(analogRead(pin));
    delay(2);
  }
  const float rawMean = static_cast<float>(total) / sampleCount;
  const float calibrated = rawMean * scale + offset;
  if (!inRange(calibrated, minimum, maximum)) return false;
  output = calibrated;
  return true;
}

BufferedReading sampleSensors() {
  BufferedReading reading;

#if FG_ENABLE_DHT22
  const float temperature = dht.readTemperature();
  const float humidity = dht.readHumidity();
  reading.hasTemperature = inRange(temperature, -80.0f, 100.0f);
  reading.hasHumidity = inRange(humidity, 0.0f, 100.0f);
  if (reading.hasTemperature) reading.temperatureC = temperature;
  if (reading.hasHumidity) reading.humidityPercent = humidity;
  if (!reading.hasTemperature || !reading.hasHumidity) {
    Serial.println("DHT22 sample unavailable or outside API bounds; omitted affected channel(s).");
  }
#endif

#if FG_ENABLE_SMOKE_ADC
  reading.hasSmoke = readCalibratedAdc(FG_SMOKE_ADC_PIN, FG_SMOKE_UNITS_PER_COUNT,
                                       FG_SMOKE_ZERO_OFFSET, 0.0f, 100000.0f,
                                       reading.smokeValue);
  if (!reading.hasSmoke) Serial.println("Smoke channel unavailable or uncalibrated; omitted.");
#endif

#if FG_ENABLE_GAS_ADC
  reading.hasGas = readCalibratedAdc(FG_GAS_ADC_PIN, FG_GAS_UNITS_PER_COUNT,
                                     FG_GAS_ZERO_OFFSET, 0.0f, 100000.0f,
                                     reading.gasValue);
  if (!reading.hasGas) Serial.println("Gas channel unavailable or uncalibrated; omitted.");
#endif

#if FG_ENABLE_BATTERY_ADC
  float measuredVolts = 0.0f;
  if (std::isfinite(FG_BATTERY_VOLTS_PER_COUNT) &&
      std::isfinite(FG_BATTERY_ZERO_OFFSET_VOLTS) &&
      std::isfinite(FG_BATTERY_EMPTY_VOLTS) && std::isfinite(FG_BATTERY_FULL_VOLTS) &&
      FG_BATTERY_FULL_VOLTS > FG_BATTERY_EMPTY_VOLTS &&
      readCalibratedAdc(FG_BATTERY_ADC_PIN, FG_BATTERY_VOLTS_PER_COUNT,
                        FG_BATTERY_ZERO_OFFSET_VOLTS,
                        FG_BATTERY_EMPTY_VOLTS, FG_BATTERY_FULL_VOLTS, measuredVolts)) {
    const float percentage = 100.0f * (measuredVolts - FG_BATTERY_EMPTY_VOLTS) /
                             (FG_BATTERY_FULL_VOLTS - FG_BATTERY_EMPTY_VOLTS);
    reading.hasBattery = inRange(percentage, 0.0f, 100.0f);
    if (reading.hasBattery) reading.batteryPercent = percentage;
  }
  if (!reading.hasBattery) Serial.println("Battery measurement unavailable or uncalibrated; omitted.");
#endif

#if FG_HAS_COORDINATES
  if (inRange(FG_LATITUDE, -90.0f, 90.0f) && inRange(FG_LONGITUDE, -180.0f, 180.0f)) {
    reading.hasCoordinates = true;
    reading.latitude = FG_LATITUDE;
    reading.longitude = FG_LONGITUDE;
  } else {
    Serial.println("Configured coordinates are invalid or unset; omitted.");
  }
#endif

  if (!makeUtcTimestamp(reading.timestamp, sizeof(reading.timestamp))) {
    Serial.println("UTC clock is not synchronized; timestamp omitted for server-side receive time.");
  }
  return reading;
}

bool buildPayload(const BufferedReading &reading, String &payload) {
  if (!validNodeId(FG_DEVICE_ID)) return false;
  const bool hasAnySensor = reading.hasTemperature || reading.hasHumidity || reading.hasSmoke || reading.hasGas;
  if (!hasAnySensor) return false;

  JsonDocument document;
  document["node_id"] = FG_DEVICE_ID;
  document["is_simulated"] = false;
  if (reading.hasTemperature && inRange(reading.temperatureC, -80.0f, 100.0f)) {
    document["temperature_c"] = reading.temperatureC;
  }
  if (reading.hasHumidity && inRange(reading.humidityPercent, 0.0f, 100.0f)) {
    document["humidity_percent"] = reading.humidityPercent;
  }
  if (reading.hasSmoke && inRange(reading.smokeValue, 0.0f, 100000.0f)) {
    document["smoke_value"] = reading.smokeValue;
  }
  if (reading.hasGas && inRange(reading.gasValue, 0.0f, 100000.0f)) {
    document["gas_value"] = reading.gasValue;
  }
  if (reading.hasBattery && inRange(reading.batteryPercent, 0.0f, 100.0f)) {
    document["battery_percent"] = reading.batteryPercent;
  }
  if (reading.hasCoordinates && inRange(reading.latitude, -90.0f, 90.0f) &&
      inRange(reading.longitude, -180.0f, 180.0f)) {
    document["latitude"] = reading.latitude;
    document["longitude"] = reading.longitude;
  }
  if (reading.timestamp[0] != '\0') document["timestamp"] = reading.timestamp;

  // A flagged but invalid-only measurement must not become an empty reading.
  const bool validSensor =
      (reading.hasTemperature && inRange(reading.temperatureC, -80.0f, 100.0f)) ||
      (reading.hasHumidity && inRange(reading.humidityPercent, 0.0f, 100.0f)) ||
      (reading.hasSmoke && inRange(reading.smokeValue, 0.0f, 100000.0f)) ||
      (reading.hasGas && inRange(reading.gasValue, 0.0f, 100000.0f));
  if (!validSensor) return false;
  payload = "";
  return serializeJson(document, payload) > 0;
}

bool validateServerResponse(const String &responseBody) {
  JsonDocument response;
  if (deserializeJson(response, responseBody) != DeserializationError::Ok) return false;
  return response["id"].is<unsigned long>() && response["id"].as<unsigned long>() > 0 &&
         response["node_id"].as<String>() == FG_DEVICE_ID &&
         response["is_simulated"].is<bool>() && !response["is_simulated"].as<bool>();
}

enum class SendResult { Accepted, RetryableFailure, Rejected };

SendResult postReading(const BufferedReading &reading) {
  String payload;
  if (!buildPayload(reading, payload)) {
    Serial.println("Sample rejected locally: invalid device ID or no valid sensor fields.");
    return SendResult::Rejected;
  }
  if (strlen(FG_BACKEND_URL) == 0 ||
      !(strncmp(FG_BACKEND_URL, "http://", 7) == 0 || strncmp(FG_BACKEND_URL, "https://", 8) == 0)) {
    Serial.println("Backend URL is missing or invalid; sample remains buffered.");
    return SendResult::RetryableFailure;
  }

  String backendOrigin = FG_BACKEND_URL;
  while (backendOrigin.endsWith("/")) backendOrigin.remove(backendOrigin.length() - 1);
  const String endpoint = backendOrigin + "/api/readings";
  for (int attempt = 0; attempt <= FG_HTTP_RETRIES; ++attempt) {
    HTTPClient http;
    http.setConnectTimeout(FG_HTTP_TIMEOUT_MS);
    http.setTimeout(FG_HTTP_TIMEOUT_MS);
    bool started = false;
    WiFiClientSecure secureClient;
    WiFiClient plainClient;
    if (strncmp(FG_BACKEND_URL, "https://", 8) == 0) {
      if (strlen(FG_BACKEND_ROOT_CA) == 0) {
        Serial.println("HTTPS refused: configure the backend root CA in local config.h.");
        return SendResult::RetryableFailure;
      }
      secureClient.setCACert(FG_BACKEND_ROOT_CA);
      started = http.begin(secureClient, endpoint);
    } else {
      started = http.begin(plainClient, endpoint);
    }
    if (!started) return SendResult::RetryableFailure;

    http.addHeader("Content-Type", "application/json");
    const int status = http.POST(payload);
    String body;
    if (status > 0) body = http.getString();
    http.end();

    if (status == 201 && validateServerResponse(body)) {
      Serial.printf("Reading accepted by API (HTTP %d).\n", status);
      return SendResult::Accepted;
    }
    if ((status >= 400 && status < 500 && status != 429) || (status >= 200 && status < 300)) {
      Serial.printf("API rejected or returned an unexpected response (HTTP %d); sample discarded.\n", status);
      return SendResult::Rejected;
    }
    Serial.printf("API request failed (HTTP %d), attempt %d/%d.\n", status, attempt + 1,
                  FG_HTTP_RETRIES + 1);
    if (attempt < FG_HTTP_RETRIES) delay(250UL << attempt);
  }
  return SendResult::RetryableFailure;
}

void beginWifi() {
  if (strlen(FG_WIFI_SSID) == 0) {
    Serial.println("Wi-Fi SSID is empty; configure local config.h before connecting.");
    return;
  }
  WiFi.mode(WIFI_STA);
  WiFi.setAutoReconnect(true);
  WiFi.begin(FG_WIFI_SSID, FG_WIFI_PASSWORD);
  lastWifiAttemptAt = millis();
  Serial.println("Wi-Fi connection started; credentials are not logged.");
}

void maintainWifi() {
  if (WiFi.status() == WL_CONNECTED) {
    if (!timeSyncRequested) {
      configTzTime("UTC0", "pool.ntp.org", "time.nist.gov");
      timeSyncRequested = true;
      Serial.println("UTC time synchronization requested.");
    }
    return;
  }
  if (strlen(FG_WIFI_SSID) == 0) return;
  if (millis() - lastWifiAttemptAt >= FG_WIFI_RETRY_INTERVAL_MS) {
    WiFi.disconnect(false, false);
    WiFi.begin(FG_WIFI_SSID, FG_WIFI_PASSWORD);
    lastWifiAttemptAt = millis();
    Serial.println("Wi-Fi reconnect requested.");
  }
}

void uploadOldestIfReady() {
  if (queueSize == 0 || WiFi.status() != WL_CONNECTED ||
      millis() - lastUploadAt < FG_UPLOAD_INTERVAL_MS) return;
  lastUploadAt = millis();
  const SendResult result = postReading(offlineQueue[queueHead]);
  if (result != SendResult::RetryableFailure) {
    queueHead = (queueHead + 1) % kQueueCapacity;
    --queueSize;
  }
}

} // namespace

void setup() {
  Serial.begin(115200);
  delay(100);
  Serial.printf("ForestGuard ESP32 firmware %s | station=%s\n", FG_FIRMWARE_VERSION,
                FG_DEVICE_ID[0] == '\0' ? "<configure device ID>" : FG_DEVICE_ID);

  if (!validNodeId(FG_DEVICE_ID)) {
    Serial.println("Invalid or empty device ID; ingestion will remain disabled until configured.");
  }
#if FG_ENABLE_DHT22
  dht.begin();
  Serial.printf("DHT22 adapter enabled on configured GPIO %d.\n", FG_DHT_PIN);
#endif
#if FG_ENABLE_SMOKE_ADC
  if (!std::isfinite(FG_SMOKE_UNITS_PER_COUNT) || !std::isfinite(FG_SMOKE_ZERO_OFFSET)) {
    Serial.println("Smoke adapter enabled but calibration is unset; channel will remain unavailable.");
  }
#endif
#if FG_ENABLE_GAS_ADC
  if (!std::isfinite(FG_GAS_UNITS_PER_COUNT) || !std::isfinite(FG_GAS_ZERO_OFFSET)) {
    Serial.println("Gas adapter enabled but calibration is unset; channel will remain unavailable.");
  }
#endif
#if FG_ENABLE_BATTERY_ADC
  if (!std::isfinite(FG_BATTERY_VOLTS_PER_COUNT) ||
      !std::isfinite(FG_BATTERY_ZERO_OFFSET_VOLTS) ||
      !std::isfinite(FG_BATTERY_EMPTY_VOLTS) || !std::isfinite(FG_BATTERY_FULL_VOLTS)) {
    Serial.println("Battery adapter enabled but circuit calibration is unset; channel will remain unavailable.");
  }
#endif
  beginWifi();
}

void loop() {
  maintainWifi();
  const unsigned long now = millis();
  if (now - lastSampleAt >= FG_SAMPLE_INTERVAL_MS) {
    lastSampleAt = now;
    const BufferedReading reading = sampleSensors();
    if (!(reading.hasTemperature || reading.hasHumidity || reading.hasSmoke || reading.hasGas)) {
      Serial.println("No valid sensor channel; nothing submitted. Check sensor/configuration.");
    } else {
      addToOfflineQueue(reading);
    }
  }
  uploadOldestIfReady();
  delay(10);
}
