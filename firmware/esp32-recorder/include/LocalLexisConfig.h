#pragma once

// Bring-up defaults. Create include/LocalLexisConfig.local.h to override
// these values without committing local Wi-Fi credentials.
#define LOCALLEXIS_WIFI_SSID ""
#define LOCALLEXIS_WIFI_PASSWORD ""
#define LOCALLEXIS_WIFI_CHANNEL 0
#define LOCALLEXIS_DEVICE_NAME "LocalLexis Recorder"

#define LOCALLEXIS_WOKWI_HUB_URL "http://host.wokwi.internal:8765"
#define LOCALLEXIS_WOKWI_PAIRING_TOKEN ""
#define LOCALLEXIS_WOKWI_TLS_SPKI_B64 ""

// Desktop/Tauri BLE provisioning UUIDs. Keep aligned with ui/src-tauri/src/ble.rs.
#define LOCALLEXIS_BLE_SERVICE_UUID "8f0d1b0a-1e5c-4d0c-9ad0-f0c4f5e9d001"
#define LOCALLEXIS_BLE_HELLO_UUID "8f0d1b0a-1e5c-4d0c-9ad0-f0c4f5e9d002"
#define LOCALLEXIS_BLE_PROVISION_RX_UUID "8f0d1b0a-1e5c-4d0c-9ad0-f0c4f5e9d003"

#if defined(LOCALLEXIS_WOKWI_SIM)
#undef LOCALLEXIS_WIFI_SSID
#undef LOCALLEXIS_WIFI_PASSWORD
#undef LOCALLEXIS_WIFI_CHANNEL
#undef LOCALLEXIS_DEVICE_NAME
#define LOCALLEXIS_WIFI_SSID "Wokwi-GUEST"
#define LOCALLEXIS_WIFI_PASSWORD ""
#define LOCALLEXIS_WIFI_CHANNEL 6
#define LOCALLEXIS_DEVICE_NAME "LocalLexis Wokwi Recorder"
#endif

#if __has_include("LocalLexisConfig.local.h")
#include "LocalLexisConfig.local.h"
#endif

#if defined(LOCALLEXIS_WOKWI_SIM) && __has_include("LocalLexisConfig.wokwi.local.h")
#include "LocalLexisConfig.wokwi.local.h"
#endif
