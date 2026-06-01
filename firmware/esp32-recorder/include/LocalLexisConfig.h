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

// microSD pins for the on-board SDMMC card slot on the Waveshare
// ESP32-S3-ePaper-1.54 V2. The slot is wired in 1-bit SDMMC mode, not SPI.
// Override per board variant in LocalLexisConfig.local.h if needed.
#ifndef LOCALLEXIS_SD_CLK
#define LOCALLEXIS_SD_CLK 39
#endif
#ifndef LOCALLEXIS_SD_CMD
#define LOCALLEXIS_SD_CMD 41
#endif
#ifndef LOCALLEXIS_SD_D0
#define LOCALLEXIS_SD_D0 40
#endif

// 1.54" ePaper panel (SSD1681 / GDEY0154D67) on the board.
// EPD_PWR is active-LOW: drive 0 to power the panel, 1 to cut it.
#ifndef LOCALLEXIS_EPD_BUSY
#define LOCALLEXIS_EPD_BUSY 8
#endif
#ifndef LOCALLEXIS_EPD_RST
#define LOCALLEXIS_EPD_RST 9
#endif
#ifndef LOCALLEXIS_EPD_DC
#define LOCALLEXIS_EPD_DC 10
#endif
#ifndef LOCALLEXIS_EPD_CS
#define LOCALLEXIS_EPD_CS 11
#endif
#ifndef LOCALLEXIS_EPD_SCK
#define LOCALLEXIS_EPD_SCK 12
#endif
#ifndef LOCALLEXIS_EPD_MOSI
#define LOCALLEXIS_EPD_MOSI 13
#endif
#ifndef LOCALLEXIS_EPD_PWR
#define LOCALLEXIS_EPD_PWR 6
#endif

// Onboard ES8311 audio codec + I2S mic, Waveshare ESP32-S3-ePaper-1.54 V2.
// Pins from waveshareteam/ESP32-S3-ePaper-1.54 board_cfg.txt. Audio_PWR active-LOW.
#ifndef LOCALLEXIS_AUDIO_SAMPLE_RATE
#define LOCALLEXIS_AUDIO_SAMPLE_RATE 16000
#endif
#ifndef LOCALLEXIS_AUDIO_PWR
#define LOCALLEXIS_AUDIO_PWR 42
#endif
#ifndef LOCALLEXIS_I2C_SDA
#define LOCALLEXIS_I2C_SDA 47
#endif
#ifndef LOCALLEXIS_I2C_SCL
#define LOCALLEXIS_I2C_SCL 48
#endif
#ifndef LOCALLEXIS_ES8311_ADDR
#define LOCALLEXIS_ES8311_ADDR 0x18
#endif
#ifndef LOCALLEXIS_I2S_MCLK
#define LOCALLEXIS_I2S_MCLK 14
#endif
#ifndef LOCALLEXIS_I2S_BCLK
#define LOCALLEXIS_I2S_BCLK 15
#endif
#ifndef LOCALLEXIS_I2S_WS
#define LOCALLEXIS_I2S_WS 38
#endif
#ifndef LOCALLEXIS_I2S_DIN
#define LOCALLEXIS_I2S_DIN 16   // mic / ASDOUT
#endif

// User-input + status LED.
#ifndef LOCALLEXIS_BOOT_BTN
#define LOCALLEXIS_BOOT_BTN 0
#endif
#ifndef LOCALLEXIS_LED
#define LOCALLEXIS_LED 3        // active-LOW
#endif

// ePaper (GxEPD2_154_D67) — same wiring as hello_screen.cpp. EPD_PWR active-LOW.
#ifndef LOCALLEXIS_EPD_BUSY
#define LOCALLEXIS_EPD_BUSY 8
#endif
#ifndef LOCALLEXIS_EPD_RST
#define LOCALLEXIS_EPD_RST 9
#endif
#ifndef LOCALLEXIS_EPD_DC
#define LOCALLEXIS_EPD_DC 10
#endif
#ifndef LOCALLEXIS_EPD_CS
#define LOCALLEXIS_EPD_CS 11
#endif
#ifndef LOCALLEXIS_EPD_SCK
#define LOCALLEXIS_EPD_SCK 12
#endif
#ifndef LOCALLEXIS_EPD_MOSI
#define LOCALLEXIS_EPD_MOSI 13
#endif
#ifndef LOCALLEXIS_EPD_PWR
#define LOCALLEXIS_EPD_PWR 6
#endif

// Per-clip size caps. SD path matches hub DEFAULT_MAX_UPLOAD_BYTES; no-SD path is a
// safe contiguous PSRAM allocation.
#ifndef LOCALLEXIS_AUDIO_SD_CAP_BYTES
#define LOCALLEXIS_AUDIO_SD_CAP_BYTES (256ULL * 1024 * 1024)
#endif
#ifndef LOCALLEXIS_AUDIO_NOSD_CAP_BYTES
#define LOCALLEXIS_AUDIO_NOSD_CAP_BYTES (4ULL * 1024 * 1024)
#endif

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
